"""Regression tests for the two reported problems:
 1. tasks were created but no data was extracted;
 2. the location picker did not offer all countries / the right states / cities / ZIP codes.
All network calls are simulated (httpx.MockTransport); the location data is the REAL bundled database."""
import asyncio
import json
import re
import time
import types
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from leadx import geo
from leadx.adapters.osm_overpass import OsmOverpassAdapter, build_query
from leadx.api import create_app
from leadx.area import locate
from leadx.categories import canonical, filters_for
from leadx.config import load_dotenv_file
from leadx.db import Store
from leadx.locations import LocationsDB
from leadx.schemas import Location

LOC = LocationsDB()


@pytest.fixture(autouse=True)
def no_nominatim_delay(monkeypatch):
    monkeypatch.setattr(geo, "settings", types.SimpleNamespace(
        nominatim_min_interval=0.0, nominatim_user_agent="t", nominatim_referer="http://x/", contact_email="t@t.test"))


# ------------------------------------------------------------------ simulated OSM servers
def osm_handler(overpass_calls: list):
    """Nominatim returns a ~10 km box; Overpass returns hotels, or a 'runtime error' for big boxes."""
    async def handler(request: httpx.Request):
        url = str(request.url)
        if "nominatim" in url:
            return httpx.Response(200, json=[{"boundingbox": ["12.90", "13.00", "77.50", "77.60"]}])
        if "overpass" in url:
            q = parse_qs(request.content.decode())["data"][0]
            overpass_calls.append(q)
            s, w, n, e = (float(x) for x in re.search(r"\(([\d.\-]+),([\d.\-]+),([\d.\-]+),([\d.\-]+)\)", q).groups())
            if (n - s) > 0.06:                            # too big for the simulated server
                return httpx.Response(200, json={"elements": [], "remark": "runtime error: Query timed out in \"query\" at line 4 after 61 seconds."})
            i = int((s * 1000) % 997)
            els = [{"type": "node", "id": 1000 + i + k, "lat": s + 0.01, "lon": w + 0.01,
                    "tags": {"name": f"Hotel {i}-{k}", "tourism": "hotel", "phone": f"+91 {i}{k}"}} for k in range(3)]
            return httpx.Response(200, json={"elements": els})
        return httpx.Response(404)
    return handler


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def wait(c, jid, statuses, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in statuses:
            return j
        time.sleep(0.05)
    raise AssertionError(f"never reached {statuses}: {j}")


def make_app(tmp_path, calls, **kw):
    # delay=0 so tests are fast
    orig = OsmOverpassAdapter.__init__

    def init(self, client, retries=3, delay=0.0, overpass_url="https://overpass-api.de/api/interpreter"):
        orig(self, client, retries=retries, delay=0.0, overpass_url=overpass_url)
    OsmOverpassAdapter.__init__ = init
    app = create_app(str(tmp_path / "t.db"), http_client=client_for(osm_handler(calls)), **kw)
    return TestClient(app), orig


# =========================================================== problem 1: data not extracted
def test_full_pipeline_with_real_osm_adapter_extracts_data(tmp_path):
    calls = []
    c, orig = make_app(tmp_path, calls)
    try:
        with c:
            body = {"keyword": "Hotel", "source": "osm",
                    "location": {"country": "India", "country_code": "IN", "state": "Karnataka", "city": "Bengaluru",
                                 "postal_code": "All zip codes"},
                    "options": {"max_places": 50, "tile_deg": 0.05, "results_per_tile": 25}}
            r = c.post("/api/jobs", json=body)
            assert r.status_code == 201, r.text
            job = wait(c, r.json()["id"], {"done", "failed"})
            assert job["status"] == "done" and job["places_found"] > 0, job
            items = c.get(f"/api/jobs/{job['id']}/places").json()["items"]
            assert items and all(p["category"] == "hotel" for p in items)
            assert "tourism" in calls[0] and "hotel" in calls[0]          # mapped category, not a name search
    finally:
        OsmOverpassAdapter.__init__ = orig


def test_overpass_timeout_is_not_silently_treated_as_empty(tmp_path):
    """HTTP 200 + 'runtime error' remark used to mean 'zero results'. Now the tile is split and re-queried."""
    calls = []

    async def run():
        ad = OsmOverpassAdapter(client_for(osm_handler(calls)), delay=0.0)
        return await ad.search("hotel", geo.Tile(12.0, 77.0, 12.2, 77.2), 100)     # 0.2 deg: too big for the fake server
    res = asyncio.run(run())
    assert len(res) > 0
    assert len(calls) > 1                        # the first query timed out, the quadrants were searched instead


def test_overpass_persistent_timeout_raises_instead_of_returning_nothing():
    async def handler(request):
        return httpx.Response(200, json={"elements": [], "remark": "runtime error: out of memory"})

    async def run():
        ad = OsmOverpassAdapter(client_for(handler), delay=0.0)
        return await ad.search("hotel", geo.Tile(12.0, 77.0, 12.03, 77.03), 10)     # too small to split further
    with pytest.raises(Exception) as e:
        asyncio.run(run())
    assert "runtime error" in str(e.value)


def test_job_never_stays_queued_when_adapter_cannot_be_built(tmp_path):
    """Google selected but no key / any adapter error: the job must end 'failed' with a readable reason."""
    def bad_factory(source):
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not configured")
    app = create_app(str(tmp_path / "t.db"), adapter_factory=bad_factory,
                     geocoder=lambda *a, **k: _bbox())
    with TestClient(app) as c:
        r = c.post("/api/jobs", json={"keyword": "x", "location": {"country": "India", "country_code": "IN"}, "source": "osm"})
        assert r.status_code == 201, r.text
        job = wait(c, r.json()["id"], {"failed"})
        assert "GOOGLE_PLACES_API_KEY" in job["error"]


async def _bbox():
    return (12.9, 77.5, 13.0, 77.6)


def test_geocoder_failure_falls_back_to_dataset_so_task_can_still_run():
    async def broken(client, *a, **k):
        raise httpx.ConnectError("blocked")
    loc = Location(country="India", country_code="IN", state="Karnataka", city="Bengaluru")
    bbox, how = asyncio.run(locate(None, LOC, broken, loc))
    assert how == "dataset-city-centre" and bbox[0] < 12.97 < bbox[2] and bbox[1] < 77.59 < bbox[3]
    state_only = Location(country="India", country_code="IN", state="Karnataka")
    bbox, how = asyncio.run(locate(None, LOC, broken, state_only))
    assert how == "dataset-state-extent" and (bbox[2] - bbox[0]) > 3


def test_zip_selection_uses_dataset_centroid_without_network():
    async def must_not_be_called(*a, **k):
        raise AssertionError("network used for a ZIP that is in the dataset")
    city = next(c for c in LOC.cities(next(s for s in LOC.states("IN") if s["name"] == "Karnataka")["id"]) if c["name"] == "Bengaluru")
    z = LOC.zips(city["id"])[0]
    loc = Location(country="India", country_code="IN", state="Karnataka", city="Bengaluru", city_id=city["id"], postal_code=z["code"])
    bbox, how = asyncio.run(locate(None, LOC, must_not_be_called, loc))
    assert how == "zip-centroid" and bbox[0] < z["lat"] < bbox[2] and (bbox[2] - bbox[0]) < 0.1


def test_all_countries_gives_clear_error():
    with pytest.raises(ValueError, match="Select a country"):
        asyncio.run(locate(None, LOC, None, Location()))


def test_stop_interrupts_email_enrichment_quickly(tmp_path):
    """Enrichment used to be one uninterruptible phase, so Stop/Delete could hang for minutes."""
    from leadx.job_runner import run_job
    from leadx.models import PlaceDTO
    store = Store(tmp_path / "e.db")
    jid = store.create_job(keyword="x", bbox=(0, 0, 0.01, 0.01), tiles_total=1, tile_deg=0.05, max_places=100,
                           per_tile=10, options={"extract_emails": True})
    store.save_tile(jid, [PlaceDTO(source="osm", source_place_id=str(i), name=f"P{i}", website=f"https://s{i}.test",
                                   phone=str(i)) for i in range(40)], 1, 100)
    seen = {"n": 0}

    class Slow:
        concurrency = 2

        async def enrich_many(self, places):
            seen["n"] += len(places)
            await asyncio.sleep(0.01)             # a real fetch awaits the network, letting Stop be noticed
            return {p.dedup_key: ("a@b.test", "found") for p in places}

    stop = {"v": False}

    class Src:
        async def search(self, *a):
            return []

    async def go():
        async def flip():
            while seen["n"] < 8:
                await asyncio.sleep(0)
            stop["v"] = True
        t = asyncio.create_task(flip())
        res = await run_job(store, jid, Src(), should_stop=lambda: stop["v"], email_enricher=Slow())
        await t
        return res
    assert asyncio.run(go()) == "paused"
    assert 0 < seen["n"] < 40 and store.has_pending_email(jid)
    # resume finishes only the remaining ones
    stop["v"] = False
    assert asyncio.run(run_job(store, jid, Src(), email_enricher=Slow())) == "done"
    assert not store.has_pending_email(jid)


def test_env_file_is_actually_loaded(tmp_path, monkeypatch):
    monkeypatch.delenv("LEADX_TEST_KEY", raising=False)
    f = tmp_path / ".env"
    f.write_text('# comment\nLEADX_TEST_KEY="hello world"\nBAD LINE\n', encoding="utf-8")
    assert load_dotenv_file(f) and __import__("os").environ["LEADX_TEST_KEY"] == "hello world"


def test_diagnostics_reports_blocked_services(tmp_path):
    async def handler(request):
        if "nominatim" in str(request.url):
            return httpx.Response(403)
        raise httpx.ConnectError("blocked")
    app = create_app(str(tmp_path / "d.db"), http_client=client_for(handler))
    with TestClient(app) as c:
        d = c.get("/api/diagnostics").json()
        nom, ovp = d["checks"]
        assert not nom["ok"] and "403" in nom["message"] and "CONTACT_EMAIL" in nom["message"]
        assert not ovp["ok"] and "cannot connect" in ovp["message"]


def test_categories_cover_common_businesses_not_just_16():
    for kw in ["dentist", "Dental Clinic", "plumbers", "gyms", "hair salon", "chartered accountant", "pizzeria", "car showroom"]:
        assert canonical(kw), kw
    q = build_query("plumber", geo.Tile(1, 2, 3, 4), 10)
    assert '"craft"="plumber"' in q
    assert filters_for("totally unknown thing")[1] == "generic"


# =========================================================== problem 2: cascading locations (REAL data)
@pytest.fixture
def api(tmp_path):
    app = create_app(str(tmp_path / "l.db"))
    with TestClient(app) as c:
        yield c


def test_all_countries_are_offered(api):
    countries = api.get("/api/locations/countries").json()
    assert len(countries) == 250
    codes = {c["code"] for c in countries}
    assert {"IN", "US", "GB", "DE", "FR", "IT", "JP", "BR", "AU", "AE", "SG", "ZA"} <= codes
    assert all(c["state_count"] >= 0 for c in countries)


def test_states_belong_only_to_the_selected_country(api):
    in_states = {s["name"] for s in api.get("/api/locations/states", params={"country": "IN"}).json()}
    us_states = {s["name"] for s in api.get("/api/locations/states", params={"country": "US"}).json()}
    assert {"Karnataka", "Maharashtra", "Gujarat", "Delhi", "Tamil Nadu", "Kerala"} <= in_states
    assert {"California", "Texas", "New York", "Florida"} <= us_states
    assert not (in_states & {"California", "Texas"}) and not (us_states & {"Karnataka", "Gujarat"})
    assert len(in_states) >= 28
    assert api.get("/api/locations/states", params={"country": "ZZ"}).status_code == 404


def test_cities_belong_only_to_the_selected_state(api):
    def state_id(cc, name):
        return next(s["id"] for s in api.get("/api/locations/states", params={"country": cc}).json() if s["name"] == name)
    ka = {c["name"] for c in api.get("/api/locations/cities", params={"state_id": state_id("IN", "Karnataka")}).json()}
    gj = {c["name"] for c in api.get("/api/locations/cities", params={"state_id": state_id("IN", "Gujarat")}).json()}
    assert "Bengaluru" in ka and "Mysuru" in ka | {"Mysuru"} and "Surat" in gj and "Ahmedabad" in gj
    assert "Surat" not in ka and "Bengaluru" not in gj
    found = api.get("/api/locations/cities", params={"state_id": state_id("IN", "Karnataka"), "q": "beng"}).json()
    assert found and all("beng" in c["name"].lower() for c in found)


def test_zip_codes_are_only_the_selected_citys(api):
    def city(cc, state, name):
        sid = next(s["id"] for s in api.get("/api/locations/states", params={"country": cc}).json() if s["name"] == state)
        return next(c for c in api.get("/api/locations/cities", params={"state_id": sid}).json() if c["name"] == name)

    blr = {z["code"] for z in api.get("/api/locations/zips", params={"city_id": city("IN", "Karnataka", "Bengaluru")["id"]}).json()}
    mum = {z["code"] for z in api.get("/api/locations/zips", params={"city_id": city("IN", "Maharashtra", "Mumbai")["id"]}).json()}
    sur = {z["code"] for z in api.get("/api/locations/zips", params={"city_id": city("IN", "Gujarat", "Surat")["id"]}).json()}
    assert len(blr) > 50 and "560001" in blr and all(z.startswith("56") for z in blr)
    assert len(mum) > 50 and all(z.startswith("40") for z in mum)
    assert len(sur) > 20 and all(z.startswith("39") for z in sur)
    assert not (blr & mum) and not (blr & sur) and not (mum & sur)           # no other city's ZIP codes

    chi = {z["code"] for z in api.get("/api/locations/zips", params={"city_id": city("US", "Illinois", "Chicago")["id"]}).json()}
    assert "60601" in chi and "46312" not in chi and "60064" not in chi      # East/North Chicago are different cities

    # same city name, different states -> different ZIP lists
    spi = {z["code"] for z in api.get("/api/locations/zips", params={"city_id": city("US", "Illinois", "Springfield")["id"]}).json()}
    spm = {z["code"] for z in api.get("/api/locations/zips", params={"city_id": city("US", "Massachusetts", "Springfield")["id"]}).json()}
    assert spi and spm and not (spi & spm)

    z = api.get("/api/locations/zips", params={"city_id": city("IN", "Karnataka", "Bengaluru")["id"], "q": "5600"}).json()
    assert z and all(x["code"].startswith("5600") for x in z)


def test_german_company_zips_do_not_leak_into_other_cities(api):
    sid = next(s["id"] for s in api.get("/api/locations/states", params={"country": "DE"}).json() if s["name"] == "Bavaria")
    munich = next(c for c in api.get("/api/locations/cities", params={"state_id": sid, "q": "Munich"}).json() if c["name"] == "Munich")
    zs = {z["code"] for z in api.get("/api/locations/zips", params={"city_id": munich["id"]}).json()}
    assert zs and all(z.startswith(("80", "81")) for z in zs)


def test_location_meta_documents_sources_and_licences(api):
    m = api.get("/api/locations/meta").json()
    assert "ODbL" in m["licenses"] and "CC BY" in m["licenses"] and m["stats"]["countries"] == 250
