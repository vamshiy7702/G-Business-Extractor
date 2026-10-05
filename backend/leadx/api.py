from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from .adapters import GooglePlacesAdapter, OsmOverpassAdapter, SourceAdapter
from .adapters.google_places import QuotaExceeded
from .area import locate
from .categories import canonical, suggestions
from .config import settings
from .db import Store
from .email_enricher import EmailEnricher
from .exporter import rows_to_csv_bytes, rows_to_xlsx_bytes
from .geo import MAX_TILES, adaptive_tile_deg, count_tiles, geocode_bbox
from .locations import LocationsDB, LocationsUnavailable
from .manager import JobManager
from .schemas import BulkDeleteRequest, CreateJobRequest, JobOut, PlaceDeleteRequest, QuoteOut, job_out

Geocoder = Callable[..., Awaitable[tuple[float, float, float, float]]]
TERMINAL = ("done", "failed", "paused", "cancelled")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"



def create_app(db_path: Optional[str] = None, adapter_factory=None,
               geocoder: Optional[Geocoder] = None, http_client: Optional[httpx.AsyncClient] = None,
               web_client: Optional[httpx.AsyncClient] = None,
               locations_path: Optional[str] = None) -> FastAPI:
    db_path = db_path or settings.db_path
    geocoder = geocoder or geocode_bbox
    max_tiles = int(os.getenv("LEADX_MAX_TILES", str(MAX_TILES)))

    def default_adapter_factory(client: httpx.AsyncClient, source: str, store: Store) -> SourceAdapter:
        if source == "osm":
            return OsmOverpassAdapter(client)
        if source == "google":
            def guard() -> None:
                # One Text Search request is reserved before it is sent. The adapter calls this
                # once per page, which makes the cap effective even with concurrent jobs.
                ok = store.try_reserve_quota(
                    "places-text-search-pro",
                    1,
                    settings.google_text_search_free_cap,
                    allow_paid=False,
                )
                if not ok:
                    raise QuotaExceeded("Google free quota reached; job paused to prevent paid usage")
            return GooglePlacesAdapter(client, api_key=settings.google_places_api_key, quota_guard=guard)
        raise ValueError(f"Unsupported source: {source}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(db_path)
        store.mark_stale()
        client = http_client or httpx.AsyncClient(
            headers={"User-Agent": settings.nominatim_user_agent, "Referer": settings.nominatim_referer},
            timeout=90,
        )
        # Separate client for fetching third-party business websites (e-mail enrichment): it must not send
        # the Nominatim Referer, and it never follows redirects by itself (see email_enricher.is_public_url).
        contact = f" (+contact: {settings.contact_email})" if settings.contact_email else ""
        web = web_client or httpx.AsyncClient(
            headers={"User-Agent": f"LeadExtractor/1.0{contact}"}, timeout=settings.email_timeout)
        locdb = LocationsDB(locations_path)
        app.state.store, app.state.client, app.state.web, app.state.locdb = store, client, web, locdb

        def factory(source: str):
            if adapter_factory is not None:
                try:
                    return adapter_factory(source)
                except TypeError:
                    # Backwards-compatible test/Phase-4 factories that accepted a client only.
                    return adapter_factory(client)
            return default_adapter_factory(client, source, store)

        app.state.manager = JobManager(
            store,
            factory,
            lambda threads: EmailEnricher(web, concurrency=threads),
            settings.max_concurrent,
        )
        yield
        await app.state.manager.shutdown()
        await client.aclose()
        await web.aclose()
        locdb.close()
        store.close()

    app = FastAPI(title="Lead Extractor API", version="1.0.0", lifespan=lifespan)
    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    def store_of(request: Request) -> Store:
        return request.app.state.store

    def job_or_404(request: Request, job_id: int):
        job = store_of(request).get_job(job_id)
        if job is None:
            raise HTTPException(404, f"Job {job_id} not found")
        return job

    def current_quote(request: Request, job) -> dict:
        if job["source"] != "google":
            return {"estimate_calls": 0, "estimate_cost_usd": 0.0, "quota_free_cap": None,
                    "quota_calls_this_month": None, "quota_remaining": None}
        store = store_of(request)
        cap = settings.google_text_search_free_cap
        calls = store.quota_calls("places-text-search-pro")
        return {
            "estimate_calls": job["estimate_calls"],
            "estimate_cost_usd": job["estimate_cost_usd"],
            "quota_free_cap": cap,
            "quota_calls_this_month": calls,
            "quota_remaining": max(0, cap - calls),
        }

    @app.get("/api/health")
    async def health(request: Request):
        store = store_of(request)
        try:
            store.conn.execute("SELECT 1").fetchone()
            return {"status": "ok"}
        except Exception as exc:
            return {"status": "degraded", "database": str(exc)}

    @app.get("/api/settings")
    async def app_settings(request: Request):
        return {
            "default_source": "osm",
            "sources": [
                {"name": "osm", "label": "OpenStreetMap / Overpass", "configured": True, "free": True},
                {"name": "google", "label": "Google Places API (New)",
                 "configured": bool(settings.google_places_api_key), "free": False},
            ],
            "google_api_key_configured": bool(settings.google_places_api_key),
            "google_pricing_region": settings.google_region,
            "google_text_search_free_cap": settings.google_text_search_free_cap,
            "google_text_search_price_per_1000": settings.google_text_search_price_per_1000,
            "max_concurrent_jobs": settings.max_concurrent,
            "max_tiles_per_job": max_tiles,
            "email_enrichment_enabled": settings.email_enabled,
        }

    @app.get("/api/quota")
    async def quota(request: Request):
        snap = store_of(request).quota_snapshot("places-text-search-pro", settings.google_text_search_free_cap)
        snap["configured"] = bool(settings.google_places_api_key)
        snap["price_per_1000_usd"] = settings.google_text_search_price_per_1000
        return snap

    async def resolve_bbox(request: Request, body: CreateJobRequest):
        """Returns (bbox, how). Raises 404 for unknown/unsupported locations, 502 if no area can be determined."""
        try:
            return await locate(request.app.state.client, request.app.state.locdb, geocoder, body.location)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Geocoding failed and no offline fallback exists for this location: {exc}")

    @app.post("/api/jobs/estimate", response_model=QuoteOut)
    async def estimate_job(body: CreateJobRequest, request: Request):
        bbox, _how = await resolve_bbox(request, body)
        effective_tile_deg = adaptive_tile_deg(bbox, body.options.tile_deg, max_tiles)
        n_tiles = count_tiles(*bbox, effective_tile_deg)
        if n_tiles > max_tiles:
            raise HTTPException(400, f"Area too large ({n_tiles} tiles, max {max_tiles}). Choose a smaller area.")
        if body.source == "osm":
            return QuoteOut(source="osm", tiles_total=n_tiles, estimated_calls=0,
                            estimated_cost_usd=0.0, warning="OpenStreetMap/Overpass is the default free source.")
        if not settings.google_places_api_key:
            raise HTTPException(400, "Google source selected but GOOGLE_PLACES_API_KEY is not configured.")
        store = store_of(request)
        calls = store.quota_calls("places-text-search-pro")
        quote = GooglePlacesAdapter(request.app.state.client, api_key=settings.google_places_api_key).estimate_cost(
            tiles_total=n_tiles,
            results_per_tile=body.options.results_per_tile,
            max_places=body.options.max_places,
            calls_this_month=calls,
        )
        return QuoteOut(source="google", tiles_total=n_tiles, estimated_calls=quote.estimated_calls,
                        estimated_cost_usd=quote.estimated_cost_usd, free_cap=quote.free_cap,
                        calls_this_month=quote.calls_this_month, remaining_free_calls=quote.remaining_free_calls,
                        sku=quote.sku, warning=quote.warning)

    @app.post("/api/jobs", response_model=JobOut, status_code=201)
    async def create_job(body: CreateJobRequest, request: Request):
        loc, opt = body.location, body.options
        bbox, area_how = await resolve_bbox(request, body)
        effective_tile_deg = adaptive_tile_deg(bbox, opt.tile_deg, max_tiles)
        n_tiles = count_tiles(*bbox, effective_tile_deg)
        if n_tiles > max_tiles:
            raise HTTPException(400, f"Area too large ({n_tiles} tiles, max {max_tiles}). Choose a smaller area.")
        store = store_of(request)
        estimate_calls = estimate_cost = quota_sku = None
        if body.source == "google":
            if not settings.google_places_api_key:
                raise HTTPException(400, "Google source selected but GOOGLE_PLACES_API_KEY is not configured.")
            calls = store.quota_calls("places-text-search-pro")
            quote = GooglePlacesAdapter(request.app.state.client, api_key=settings.google_places_api_key).estimate_cost(
                tiles_total=n_tiles, results_per_tile=opt.results_per_tile,
                max_places=opt.max_places, calls_this_month=calls)
            if quote.estimated_calls > quote.remaining_free_calls:
                raise HTTPException(402, {
                    "message": "This job would exceed the configured Google free quota. "
                               "Reduce the search size or wait for the monthly reset.",
                    "estimated_calls": quote.estimated_calls,
                    "remaining_free_calls": quote.remaining_free_calls,
                    "estimated_paid_cost_usd": quote.estimated_cost_usd,
                })
            estimate_calls, estimate_cost, quota_sku = quote.estimated_calls, quote.estimated_cost_usd, quote.sku

        options = opt.model_dump()
        options["area_source"] = area_how       # how the search area was determined (transparency)
        job_id = store.create_job(
            keyword=body.keyword.strip(), bbox=bbox, tiles_total=n_tiles, tile_deg=effective_tile_deg,
            max_places=opt.max_places, per_tile=min(opt.results_per_tile, 60) if body.source == "google" else opt.results_per_tile,
            city=loc.city, state=loc.state, country=loc.country, postal_code=loc.postal_code,
            source=body.source, options=options, estimate_calls=estimate_calls,
            estimate_cost_usd=estimate_cost, quota_sku=quota_sku)
        request.app.state.manager.start(job_id)
        job = store.get_job(job_id)
        return job_out(job, current_quote(request, job))

    @app.get("/api/jobs", response_model=list[JobOut])
    async def list_jobs(request: Request, limit: int = Query(50, ge=1, le=200)):
        store = store_of(request)
        return [job_out(j, current_quote(request, j)) for j in store.list_jobs(limit)]

    @app.get("/api/jobs/{job_id}", response_model=JobOut)
    async def get_job(job_id: int, request: Request):
        job = job_or_404(request, job_id)
        return job_out(job, current_quote(request, job))

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobOut)
    async def cancel_job(job_id: int, request: Request):
        job_or_404(request, job_id)
        request.app.state.manager.stop(job_id)
        return job_out(store_of(request).get_job(job_id), current_quote(request, store_of(request).get_job(job_id)))

    @app.post("/api/jobs/{job_id}/resume", response_model=JobOut)
    async def resume_job(job_id: int, request: Request):
        job = job_or_404(request, job_id)
        if job["status"] == "done":
            raise HTTPException(409, "Job is already done")
        if job["source"] == "google" and not settings.google_places_api_key:
            raise HTTPException(400, "Google source selected but GOOGLE_PLACES_API_KEY is not configured.")
        request.app.state.manager.start(job_id)
        return job_out(store_of(request).get_job(job_id), current_quote(request, store_of(request).get_job(job_id)))

    @app.delete("/api/jobs/{job_id}", status_code=204)
    async def delete_job(job_id: int, request: Request):
        job_or_404(request, job_id)
        await request.app.state.manager.stop_and_wait(job_id)
        store_of(request).delete_job(job_id)
        return Response(status_code=204)

    @app.post("/api/jobs/bulk-delete")
    async def bulk_delete_jobs(body: BulkDeleteRequest, request: Request):
        store = store_of(request)
        deleted: list[int] = []
        missing: list[int] = []
        for job_id in body.ids:
            if store.get_job(job_id) is None:
                missing.append(job_id)
                continue
            await request.app.state.manager.stop_and_wait(job_id)
            # The job may have become terminal while we waited; deletion is now safe.
            if store.get_job(job_id) is not None:
                store.delete_job(job_id)
                deleted.append(job_id)
        return {"deleted": deleted, "missing": missing}

    @app.post("/api/jobs/{job_id}/enrich", response_model=JobOut)
    async def enrich_job(job_id: int, request: Request):
        """Find emails for a finished (or paused) task. Runs in the background like a normal task."""
        job = job_or_404(request, job_id)
        store = store_of(request)
        if request.app.state.manager.is_active(job_id):
            raise HTTPException(409, "Wait for the search to finish before enrichment.")
        if not settings.email_enabled:
            raise HTTPException(400, "Email enrichment is disabled by configuration.")
        if not store.has_pending_email(job_id):
            raise HTTPException(409, "Every result has already been checked for an email address.")
        options = json.loads(job["options_json"] or "{}")
        options["extract_emails"] = True
        with store.conn:
            store.conn.execute("UPDATE jobs SET options_json=? WHERE id=?", (json.dumps(options, separators=(",", ":")), job_id))
        request.app.state.manager.start(job_id)
        job = store.get_job(job_id)
        return job_out(job, current_quote(request, job))

    @app.get("/api/jobs/{job_id}/places")
    async def list_places(job_id: int, request: Request,
                          offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
                          has_phone: Optional[bool] = None, has_email: Optional[bool] = None,
                          has_website: Optional[bool] = None,
                          min_rating: Optional[float] = Query(None, ge=0, le=5), q: str = ""):
        job_or_404(request, job_id)
        items, total = store_of(request).query_places(
            job_id, offset=offset, limit=limit, has_phone=has_phone,
            has_email=has_email, has_website=has_website, min_rating=min_rating, q=q)
        return {"total": total, "offset": offset, "limit": limit, "items": items}

    @app.post("/api/jobs/{job_id}/places/delete")
    async def delete_selected_places(job_id: int, body: PlaceDeleteRequest, request: Request):
        job_or_404(request, job_id)
        await request.app.state.manager.stop_and_wait(job_id) if request.app.state.manager.is_active(job_id) else None
        deleted = store_of(request).delete_places(job_id, body.ids)
        return {"deleted": deleted, "count": len(deleted)}

    @app.post("/api/jobs/{job_id}/places/delete-all")
    async def delete_all_places(job_id: int, request: Request):
        job_or_404(request, job_id)
        await request.app.state.manager.stop_and_wait(job_id) if request.app.state.manager.is_active(job_id) else None
        deleted = store_of(request).delete_places(job_id, None)
        return {"deleted": deleted, "count": len(deleted)}

    @app.get("/api/jobs/{job_id}/export")
    async def export_job(job_id: int, request: Request,
                         format: str = Query("csv", pattern="^(csv|xlsx)$"),
                         has_phone: Optional[bool] = None, has_email: Optional[bool] = None,
                         has_website: Optional[bool] = None,
                         min_rating: Optional[float] = Query(None, ge=0, le=5), q: str = "",
                         columns: str = "", separator: str = Query(",", pattern="^[,;]$")):
        job_or_404(request, job_id)
        rows, _ = store_of(request).query_places(
            job_id, offset=0, limit=-1, has_phone=has_phone, has_email=has_email,
            has_website=has_website, min_rating=min_rating, q=q)
        requested = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
        if format == "xlsx":
            body = rows_to_xlsx_bytes(rows, requested)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            body, media = rows_to_csv_bytes(rows, requested, separator), "text/csv; charset=utf-8"
        return Response(body, media_type=media, headers={
            "Content-Disposition": f'attachment; filename="leads-job-{job_id}.{format}"'})

    @app.get("/api/jobs/{job_id}/stream")
    async def stream_job(job_id: int, request: Request, after: int = Query(0, ge=0)):
        job_or_404(request, job_id)
        store, manager = store_of(request), request.app.state.manager

        async def gen():
            last_id, last_sig = after, None
            while True:
                if await request.is_disconnected():
                    return
                job = store.get_job(job_id)
                if job is None:
                    return
                new = store.places_after(job_id, last_id, 100)
                if new:
                    last_id = new[-1]["id"]
                sig = (job["status"], job["tiles_done"], job["places_found"], *store.email_counts(job_id))
                if new or sig != last_sig:
                    last_sig = sig
                    yield _sse("progress", {"job": job_out(job, current_quote(request, job)).model_dump(), "new_places": new})
                if len(new) == 100:
                    continue
                if job["status"] in TERMINAL and not manager.is_active(job_id):
                    yield _sse("end", {"status": job["status"]})
                    return
                await asyncio.sleep(1)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- locations (cascading Country -> State -> City -> ZIP) -------------------------------------
    def locdb_of(request: Request) -> LocationsDB:
        db: LocationsDB = request.app.state.locdb
        if not db.available:
            raise HTTPException(503, "Location database is missing. Run: python scripts/build_locations.py")
        return db

    @app.get("/api/locations/countries")
    async def loc_countries(request: Request):
        return locdb_of(request).countries()

    @app.get("/api/locations/states")
    async def loc_states(request: Request, country: str = Query(..., min_length=2, max_length=3)):
        db = locdb_of(request)
        code = db.country_code(country)
        if code is None:
            raise HTTPException(404, f"Unknown country: {country}")
        return db.states(code)

    @app.get("/api/locations/cities")
    async def loc_cities(request: Request, state_id: int, q: str = "", limit: int = Query(5000, ge=1, le=20000)):
        return locdb_of(request).cities(state_id, q.strip(), limit)

    @app.get("/api/locations/zips")
    async def loc_zips(request: Request, city_id: int, q: str = ""):
        """ZIP/postal codes that belong to THIS city only (never another city's)."""
        return locdb_of(request).zips(city_id, q.strip())

    @app.get("/api/locations/meta")
    async def loc_meta(request: Request):
        return locdb_of(request).meta()

    # ---- categories & diagnostics ------------------------------------------------------------------
    @app.get("/api/categories")
    async def categories(source: str = "osm"):
        return {"suggestions": suggestions(),
                "note": "Unlisted keywords are searched by business name / tag value; Google gives fuller coverage for niche categories."}

    @app.get("/api/categories/check")
    async def category_check(keyword: str):
        return {"keyword": keyword, "mapped": canonical(keyword) is not None, "canonical": canonical(keyword)}

    @app.get("/api/diagnostics")
    async def diagnostics(request: Request):
        """Checks, from THIS machine, that the services extraction depends on are reachable. A blocked
        Overpass/Nominatim (firewall, VPN, bad User-Agent) is the usual reason for tasks that finish with no data."""
        import time
        client: httpx.AsyncClient = request.app.state.client

        async def probe(name: str, method: str, url: str, **kw):
            t0 = time.perf_counter()
            try:
                r = await client.request(method, url, timeout=15, **kw)
                ms = int((time.perf_counter() - t0) * 1000)
                ok = r.status_code == 200
                msg = "reachable" if ok else (
                    "403 Forbidden: set CONTACT_EMAIL and NOMINATIM_USER_AGENT in backend/.env" if r.status_code == 403
                    else f"HTTP {r.status_code}")
                return {"service": name, "ok": ok, "status": r.status_code, "ms": ms, "message": msg}
            except httpx.HTTPError as exc:
                return {"service": name, "ok": False, "status": None, "ms": int((time.perf_counter() - t0) * 1000),
                        "message": f"{type(exc).__name__}: cannot connect (network/firewall/VPN?)"}

        headers = {"User-Agent": settings.nominatim_user_agent, "Referer": settings.nominatim_referer}
        nom, ovp = await asyncio.gather(
            probe("Nominatim (geocoding)", "GET", "https://nominatim.openstreetmap.org/search",
                  params={"q": "Paris", "format": "json", "limit": 1}, headers=headers),
            probe("Overpass (OpenStreetMap data)", "GET", "https://overpass-api.de/api/status", headers=headers),
        )
        db = request.app.state.locdb
        return {"checks": [nom, ovp],
                "google_configured": bool(settings.google_places_api_key),
                "contact_email_set": bool(settings.contact_email),
                "locations_database": db.available,
                "env_file_loaded_hint": "Settings are read from backend/.env at startup; restart the backend after editing it."}

    return app


app = create_app()
