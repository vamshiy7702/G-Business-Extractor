from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

from .adapters import OsmOverpassAdapter
from .db import Store
from .exporter import to_csv
from .geo import MAX_TILES, count_tiles, geocode_bbox
from .job_runner import run_job


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="leadx", description="Find business leads from OpenStreetMap.")
    p.add_argument("--db", default="leadx.db", help="SQLite file (default: leadx.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="create a job and run it")
    r.add_argument("keyword", help='e.g. "dentist", "restaurant"')
    r.add_argument("--city", required=True)
    r.add_argument("--state", default="")
    r.add_argument("--country", default="", help="2-letter code, e.g. IN")
    r.add_argument("--limit", type=int, default=200, help="max places to collect")
    r.add_argument("--per-tile", type=int, default=200)
    r.add_argument("--tile-deg", type=float, default=0.05, help="tile size in degrees (~5.5km)")
    r.add_argument("--out", default="", help="also export CSV when finished")

    rs = sub.add_parser("resume", help="continue a paused/failed job")
    rs.add_argument("job_id", type=int)
    rs.add_argument("--out", default="")

    sub.add_parser("jobs", help="list jobs")

    ex = sub.add_parser("export", help="export a job's places to CSV")
    ex.add_argument("job_id", type=int)
    ex.add_argument("--out", default="leads.csv")
    return p


def _client() -> httpx.AsyncClient:
    contact = os.getenv("CONTACT_EMAIL", "")
    user_agent = os.getenv("NOMINATIM_USER_AGENT", "LeadExtractor/1.0")
    referer = os.getenv("NOMINATIM_REFERER", "http://localhost:3000/")
    if contact:
        user_agent = f"{user_agent} (contact: {contact})"
    return httpx.AsyncClient(headers={"User-Agent": user_agent, "Referer": referer}, timeout=90)


def _progress(done: int, total: int, found: int) -> None:
    print(f"  tile {done}/{total} - {found} unique places", flush=True)


def _finish(store: Store, job_id: int, status: str, out: str) -> int:
    job = store.get_job(job_id)
    if status == "done":
        if out:
            to_csv(list(store.iter_places(job_id)), out)
            print(f"Exported {job['places_found']} places to {out}")
        print(f"Job {job_id} done: {job['places_found']} places.")
        return 0
    print(f"Job {job_id} {status}: {job['error'] or ''}\nResume with: leadx resume {job_id}")
    return 1


async def cmd_run(store: Store, a) -> int:
    async with _client() as client:
        print(f"Locating {a.city}...")
        bbox = await geocode_bbox(client, a.city, a.state, a.country)
        n_tiles = count_tiles(*bbox, a.tile_deg)
        if n_tiles > MAX_TILES:
            raise ValueError(f"Area too large ({n_tiles} tiles, max {MAX_TILES}); increase --tile-deg")
        job_id = store.create_job(keyword=a.keyword, bbox=bbox, tiles_total=n_tiles,
                                  tile_deg=a.tile_deg, max_places=a.limit, per_tile=a.per_tile,
                                  city=a.city, state=a.state, country=a.country)
        print(f"Job {job_id}: {n_tiles} tiles, searching '{a.keyword}'...")
        status = await run_job(store, job_id, OsmOverpassAdapter(client), _progress)
    return _finish(store, job_id, status, a.out)


async def cmd_resume(store: Store, a) -> int:
    job = store.get_job(a.job_id)
    if job is None:
        print(f"No job {a.job_id}", file=sys.stderr)
        return 1
    print(f"Resuming job {a.job_id} from tile {job['tiles_done'] + 1}/{job['tiles_total']}...")
    async with _client() as client:
        status = await run_job(store, a.job_id, OsmOverpassAdapter(client), _progress)
    return _finish(store, a.job_id, status, a.out)


def cmd_jobs(store: Store) -> int:
    print(f"{'ID':>3}  {'STATUS':8} {'TILES':>9} {'PLACES':>6}  KEYWORD / LOCATION")
    for j in store.list_jobs():
        print(f"{j['id']:>3}  {j['status']:8} {j['tiles_done']:>4}/{j['tiles_total']:<4} "
              f"{j['places_found']:>6}  {j['keyword']} / {j['city']}")
    return 0


def cmd_export(store: Store, a) -> int:
    if store.get_job(a.job_id) is None:
        print(f"No job {a.job_id}", file=sys.stderr)
        return 1
    places = list(store.iter_places(a.job_id))
    to_csv(places, a.out)
    print(f"Exported {len(places)} places to {a.out}")
    return 0


def main(argv=None) -> None:
    a = build_parser().parse_args(argv)
    store = Store(a.db)
    try:
        if a.cmd == "run":
            code = asyncio.run(cmd_run(store, a))
        elif a.cmd == "resume":
            code = asyncio.run(cmd_resume(store, a))
        elif a.cmd == "jobs":
            code = cmd_jobs(store)
        else:
            code = cmd_export(store, a)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        print("\nPaused. Progress is saved; run `leadx jobs` to see the job id, then `leadx resume <id>`.")
        code = 130
    finally:
        store.close()
    sys.exit(code)
