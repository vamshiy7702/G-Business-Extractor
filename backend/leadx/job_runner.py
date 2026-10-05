from __future__ import annotations

import asyncio
import json
from typing import Callable, Optional

from .adapters.base import SourceAdapter
from .adapters.google_places import QuotaExceeded
from .db import Store
from .email_enricher import EmailEnricher
from .geo import make_tiles
from .models import PlaceDTO


def _options(job) -> dict:
    try:
        return json.loads(job["options_json"] or "{}")
    except Exception:
        return {}


async def _enrich_phase(store: Store, job_id: int, enricher: EmailEnricher,
                        should_stop: Callable[[], bool]) -> bool:
    """Look up emails in small batches. Each batch is saved immediately and `should_stop` is checked between
    batches, so Stop / Delete take effect quickly and a restart resumes with the still-pending places.
    Returns True when every place has been processed."""
    batch_size = max(4, enricher.concurrency * 2)
    while True:
        pending = [r for r in store.places_for_enrichment(job_id) if r["email_status"] == "pending"]
        if not pending:
            return True
        if should_stop():
            return False
        chunk = pending[:batch_size]
        dtos = [PlaceDTO(**{k: row[k] for k in PlaceDTO.columns()}) for row in chunk]
        results = await enricher.enrich_many(dtos)
        for row, dto in zip(chunk, dtos):
            email, status = results.get(dto.dedup_key, ("", "error"))
            if not email and dto.email:
                email, status = dto.email, "found"
            if status not in ("found", "none", "error"):
                status = "error"                      # guarantees the place leaves 'pending' (no endless loop)
            store.update_place_email(row["id"], email, status)


async def run_job(store: Store, job_id: int, adapter: SourceAdapter | Callable[[], SourceAdapter] | None,
                  on_progress: Optional[Callable[[int, int, int], None]] = None,
                  should_stop: Callable[[], bool] = lambda: False,
                  email_enricher: EmailEnricher | None = None) -> str:
    job = store.get_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    options = _options(job)
    want_emails = bool(options.get("extract_emails")) and email_enricher is not None
    if job["status"] == "done" and not (want_emails and store.has_pending_email(job_id)):
        return "done"
    tiles = make_tiles(job["south"], job["west"], job["north"], job["east"], job["tile_deg"])
    store.set_status(job_id, "running", error=None)
    try:
        total = job["places_found"]
        source: SourceAdapter | None = adapter if hasattr(adapter, "search") else None
        for idx in range(job["tiles_done"], len(tiles)):
            if total >= job["max_places"]:
                break
            if should_stop():
                store.set_status(job_id, "paused")
                return "paused"
            if source is None:
                source = adapter() if callable(adapter) else None      # built lazily, inside the try block
                if source is None:
                    raise RuntimeError("No data source adapter is available for this task")
            found = await source.search(job["keyword"], tiles[idx], job["per_tile"])
            total = store.save_tile(job_id, found, idx + 1, job["max_places"])
            if on_progress:
                on_progress(idx + 1, len(tiles), total)

        if want_emails and not await _enrich_phase(store, job_id, email_enricher, should_stop):
            store.set_status(job_id, "paused")
            return "paused"
        store.set_status(job_id, "done")
        return "done"
    except asyncio.CancelledError:
        store.set_status(job_id, "paused")
        raise
    except QuotaExceeded as exc:
        store.set_status(job_id, "paused", error=str(exc))
        return "paused"
    except Exception as exc:
        store.set_status(job_id, "failed", error=f"{type(exc).__name__}: {exc}")
        return "failed"
