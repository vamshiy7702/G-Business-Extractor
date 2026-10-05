import asyncio

import pytest

from leadx.adapters.osm_overpass import parse_element
from leadx.db import Store
from leadx.geo import make_tiles
from leadx.job_runner import run_job

BBOX = (12.0, 77.0, 12.3, 77.3)  # 3x3 = 9 tiles at 0.1 deg


def place(i: int):
    return parse_element({"type": "node", "id": i, "lat": 12.0, "lon": 77.0,
                          "tags": {"name": f"Clinic {i}", "amenity": "dentist", "phone": f"+91 {i}"}})


class FakeAdapter:
    """Returns 2 unique places per tile (+1 duplicate of tile 0's first). Can fail on a tile."""
    name = "fake"

    def __init__(self, fail_on_call: int | None = None):
        self.calls = 0
        self.fail_on_call = fail_on_call

    async def search(self, keyword, tile, limit):
        self.calls += 1
        if self.fail_on_call == self.calls:
            raise RuntimeError("overpass down")
        base = self.calls * 10
        return [place(base), place(base + 1), place(0)]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def new_job(store, max_places=500):
    n = len(make_tiles(*BBOX, 0.1))
    return store.create_job(keyword="dentist", bbox=BBOX, tiles_total=n, tile_deg=0.1,
                            max_places=max_places, per_tile=50, city="Test")


def test_full_run_dedups_and_completes(store):
    jid = new_job(store)
    assert asyncio.run(run_job(store, jid, FakeAdapter())) == "done"
    job = store.get_job(jid)
    assert job["tiles_done"] == 9 and job["status"] == "done"
    assert job["places_found"] == 9 * 2 + 1          # place(0) kept only once
    assert store.count_places(jid) == job["places_found"]


def test_failure_then_resume_continues_without_duplicates(store):
    jid = new_job(store)
    assert asyncio.run(run_job(store, jid, FakeAdapter(fail_on_call=4))) == "failed"
    job = store.get_job(jid)
    assert job["status"] == "failed" and job["tiles_done"] == 3
    assert "overpass down" in job["error"]

    resumed = FakeAdapter()
    assert asyncio.run(run_job(store, jid, resumed)) == "done"
    assert resumed.calls == 6                        # only the 6 remaining tiles
    assert store.get_job(jid)["tiles_done"] == 9
    assert store.count_places(jid) == store.get_job(jid)["places_found"]


def test_stops_at_max_places(store):
    jid = new_job(store, max_places=5)
    asyncio.run(run_job(store, jid, FakeAdapter()))
    assert store.count_places(jid) == 5 and store.get_job(jid)["status"] == "done"


def test_pause_via_should_stop_then_resume(store):
    jid = new_job(store)
    ticks = iter([False, False, True])
    assert asyncio.run(run_job(store, jid, FakeAdapter(), should_stop=lambda: next(ticks))) == "paused"
    assert store.get_job(jid)["tiles_done"] == 2
    assert asyncio.run(run_job(store, jid, FakeAdapter())) == "done"


def test_done_job_is_not_rerun(store):
    jid = new_job(store)
    asyncio.run(run_job(store, jid, FakeAdapter()))
    a = FakeAdapter()
    assert asyncio.run(run_job(store, jid, a)) == "done" and a.calls == 0


def test_jobs_are_isolated_and_listed(store):
    a, b = new_job(store), new_job(store)
    asyncio.run(run_job(store, a, FakeAdapter()))
    assert store.count_places(b) == 0
    assert [j["id"] for j in store.list_jobs()] == [b, a]
    assert len(list(store.iter_places(a, offset=2, limit=3))) == 3
