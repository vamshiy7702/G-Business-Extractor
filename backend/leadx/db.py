from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .models import PlaceDTO

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  keyword TEXT NOT NULL,
  city TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT '',
  postal_code TEXT NOT NULL DEFAULT '',
  country TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'osm',
  status TEXT NOT NULL DEFAULT 'queued',
  south REAL NOT NULL,
  west REAL NOT NULL,
  north REAL NOT NULL,
  east REAL NOT NULL,
  tile_deg REAL NOT NULL,
  max_places INTEGER NOT NULL,
  per_tile INTEGER NOT NULL,
  options_json TEXT NOT NULL DEFAULT '{}',
  tiles_total INTEGER NOT NULL DEFAULT 0,
  tiles_done INTEGER NOT NULL DEFAULT 0,
  places_found INTEGER NOT NULL DEFAULT 0,
  estimate_calls INTEGER,
  estimate_cost_usd REAL,
  quota_sku TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS places (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  dedup_key TEXT NOT NULL,
  soft_key TEXT,
  source TEXT NOT NULL,
  source_place_id TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  category TEXT DEFAULT '',
  address TEXT DEFAULT '',
  city TEXT DEFAULT '',
  state TEXT DEFAULT '',
  postal_code TEXT DEFAULT '',
  country TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  email TEXT DEFAULT '',
  website TEXT DEFAULT '',
  lat REAL,
  lng REAL,
  rating REAL,
  email_status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS quota_usage (
  month TEXT NOT NULL,
  sku TEXT NOT NULL,
  calls INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(month, sku)
);
"""

PLACE_COLS = PlaceDTO.columns()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = "leadx.db"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _columns(self, table: str) -> set[str]:
        return {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}

    def _migrate(self) -> None:
        with self.conn:
            jobs = self._columns("jobs")
            if "postal_code" not in jobs:
                self.conn.execute("ALTER TABLE jobs ADD COLUMN postal_code TEXT NOT NULL DEFAULT ''")
            if "options_json" not in jobs:
                self.conn.execute("ALTER TABLE jobs ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'")
            for col, typ in (("estimate_calls", "INTEGER"), ("estimate_cost_usd", "REAL"), ("quota_sku", "TEXT")):
                if col not in jobs:
                    self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
            places = self._columns("places")
            additions = {
                "soft_key": "TEXT",
                "source_place_id": "TEXT NOT NULL DEFAULT ''",
                "category": "TEXT DEFAULT ''",
                "address": "TEXT DEFAULT ''",
                "city": "TEXT DEFAULT ''",
                "state": "TEXT DEFAULT ''",
                "postal_code": "TEXT DEFAULT ''",
                "country": "TEXT DEFAULT ''",
                "phone": "TEXT DEFAULT ''",
                "email": "TEXT DEFAULT ''",
                "website": "TEXT DEFAULT ''",
                "lat": "REAL",
                "lng": "REAL",
                "rating": "REAL",
                "email_status": "TEXT NOT NULL DEFAULT 'pending'",
                "created_at": "TEXT NOT NULL DEFAULT ''",
            }
            for col, typ in additions.items():
                if col not in places:
                    self.conn.execute(f"ALTER TABLE places ADD COLUMN {col} {typ}")
            self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_places_job_dedup ON places(job_id, dedup_key)")
            self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_places_job_soft ON places(job_id, soft_key)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_places_job ON places(job_id, id)")

    def close(self) -> None:
        self.conn.close()

    def create_job(self, *, keyword: str, bbox: tuple[float, float, float, float],
                   tiles_total: int, tile_deg: float, max_places: int, per_tile: int,
                   city: str = "", state: str = "", country: str = "", postal_code: str = "",
                   source: str = "osm", options: Optional[dict] = None,
                   estimate_calls: int | None = None, estimate_cost_usd: float | None = None,
                   quota_sku: str | None = None) -> int:
        s, w, n, e = bbox
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO jobs (keyword, city, state, postal_code, country, source, status,
                   south, west, north, east, tile_deg, max_places, per_tile, options_json,
                   tiles_total, estimate_calls, estimate_cost_usd, quota_sku, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (keyword, city, state, postal_code, country, source, "queued", s, w, n, e,
                 tile_deg, max_places, per_tile, json.dumps(options or {}, separators=(",", ":")),
                 tiles_total, estimate_calls, estimate_cost_usd, quota_sku, now, now))
        return int(cur.lastrowid)

    def get_job(self, job_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def list_jobs(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def set_status(self, job_id: int, status: str, error: Optional[str] = None) -> None:
        finished = _now() if status in ("done", "failed", "cancelled") else None
        with self.conn:
            self.conn.execute(
                "UPDATE jobs SET status=?, error=?, updated_at=?, finished_at=? WHERE id=?",
                (status, error, _now(), finished, job_id))

    def save_tile(self, job_id: int, places: list[PlaceDTO], tiles_done: int, max_places: int) -> int:
        cols = ", ".join(PLACE_COLS)
        marks = ", ".join("?" for _ in PLACE_COLS)
        with self.conn:
            total = self.conn.execute("SELECT COUNT(*) FROM places WHERE job_id=?", (job_id,)).fetchone()[0]
            for place in places:
                if total >= max_places:
                    break
                values = [getattr(place, c) for c in PLACE_COLS]
                cur = self.conn.execute(
                    f"INSERT OR IGNORE INTO places (job_id, dedup_key, soft_key, {cols}) VALUES (?,?,?,{marks})",
                    (job_id, place.dedup_key, place.soft_key, *values))
                total += cur.rowcount
            self.conn.execute(
                "UPDATE jobs SET tiles_done=?, places_found=?, updated_at=? WHERE id=?",
                (tiles_done, total, _now(), job_id))
        return total

    def count_places(self, job_id: int) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM places WHERE job_id=?", (job_id,)).fetchone()[0])

    def iter_places(self, job_id: int, offset: int = 0, limit: int = -1) -> Iterator[PlaceDTO]:
        cols = ", ".join(PLACE_COLS)
        rows = self.conn.execute(f"SELECT {cols} FROM places WHERE job_id=? ORDER BY id LIMIT ? OFFSET ?",
                                 (job_id, limit, offset))
        for row in rows:
            yield PlaceDTO(**dict(row))

    def query_places(self, job_id: int, *, offset: int = 0, limit: int = 100,
                     has_phone=None, has_email=None, has_website=None,
                     min_rating: float | None = None, q: str = "") -> tuple[list[dict], int]:
        where = ["job_id=?"]
        args: list = [job_id]
        for flag, col in ((has_phone, "phone"), (has_email, "email"), (has_website, "website")):
            if flag is True:
                where.append(f"COALESCE({col}, '') <> ''")
            elif flag is False:
                where.append(f"COALESCE({col}, '') = ''")
        if min_rating is not None:
            where.append("rating >= ?")
            args.append(min_rating)
        if q:
            where.append("(name LIKE ? OR category LIKE ? OR address LIKE ? OR city LIKE ? OR phone LIKE ? OR email LIKE ?)")
            args.extend([f"%{q}%"] * 6)
        clause = " AND ".join(where)
        total = int(self.conn.execute(f"SELECT COUNT(*) FROM places WHERE {clause}", args).fetchone()[0])
        cols = ", ".join(["id", *PLACE_COLS])
        rows = self.conn.execute(
            f"SELECT {cols} FROM places WHERE {clause} ORDER BY id LIMIT ? OFFSET ?",
            [*args, limit, offset]).fetchall()
        return [dict(r) for r in rows], total

    def places_after(self, job_id: int, last_id: int, limit: int = 100) -> list[dict]:
        cols = ", ".join(["id", *PLACE_COLS])
        rows = self.conn.execute(
            f"SELECT {cols} FROM places WHERE job_id=? AND id>? ORDER BY id LIMIT ?",
            (job_id, last_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def delete_places(self, job_id: int, ids: list[int] | None = None) -> list[int]:
        if ids is None:
            rows = self.conn.execute("SELECT id FROM places WHERE job_id=?", (job_id,)).fetchall()
        else:
            ids = list(dict.fromkeys(int(x) for x in ids))
            if not ids:
                return []
            marks = ",".join("?" for _ in ids)
            rows = self.conn.execute(f"SELECT id FROM places WHERE job_id=? AND id IN ({marks})", [job_id, *ids]).fetchall()
        deleted = [int(r[0]) for r in rows]
        if deleted:
            marks = ",".join("?" for _ in deleted)
            with self.conn:
                self.conn.execute(f"DELETE FROM places WHERE job_id=? AND id IN ({marks})", [job_id, *deleted])
                remaining = self.conn.execute("SELECT COUNT(*) FROM places WHERE job_id=?", (job_id,)).fetchone()[0]
                self.conn.execute("UPDATE jobs SET places_found=?, updated_at=? WHERE id=?", (remaining, _now(), job_id))
        return deleted

    def update_place_email(self, place_id: int, email: str, email_status: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE places SET email=?, email_status=? WHERE id=?",
                              (email, email_status, place_id))

    def mark_email_pending(self, job_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE places SET email_status='pending' WHERE job_id=? AND email=''", (job_id,))

    def places_for_enrichment(self, job_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, name, category, address, city, state, postal_code, country, phone, email, website, lat, lng, rating, source, source_place_id, email_status FROM places WHERE job_id=? ORDER BY id",
            (job_id,)).fetchall()

    def email_counts(self, job_id: int) -> tuple[int, int]:
        """(places with an e-mail, places still waiting for a lookup)."""
        r = self.conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN email<>'' THEN 1 ELSE 0 END),0), "
            "COALESCE(SUM(CASE WHEN email_status='pending' THEN 1 ELSE 0 END),0) FROM places WHERE job_id=?",
            (job_id,)).fetchone()
        return int(r[0]), int(r[1])

    def has_pending_email(self, job_id: int) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM places WHERE job_id=? AND email_status='pending' LIMIT 1", (job_id,)).fetchone() is not None

    def quota_calls(self, sku: str, month: str | None = None) -> int:
        month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        row = self.conn.execute("SELECT calls FROM quota_usage WHERE month=? AND sku=?", (month, sku)).fetchone()
        return int(row[0]) if row else 0

    def try_reserve_quota(self, sku: str, calls: int, free_cap: int, allow_paid: bool = False, month: str | None = None) -> bool:
        month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        now = _now()
        with self.conn:
            row = self.conn.execute("SELECT calls FROM quota_usage WHERE month=? AND sku=?", (month, sku)).fetchone()
            current = int(row[0]) if row else 0
            if not allow_paid and current + calls > free_cap:
                return False
            self.conn.execute(
                "INSERT INTO quota_usage(month, sku, calls, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(month, sku) DO UPDATE SET calls=calls+excluded.calls, updated_at=excluded.updated_at",
                (month, sku, calls, now))
            return True

    def add_quota_calls(self, sku: str, calls: int, month: str | None = None) -> int:
        month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        now = _now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO quota_usage(month, sku, calls, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(month, sku) DO UPDATE SET calls=calls+excluded.calls, updated_at=excluded.updated_at",
                (month, sku, calls, now))
        return self.quota_calls(sku, month)

    def quota_snapshot(self, sku: str, free_cap: int) -> dict:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        calls = self.quota_calls(sku, month)
        return {
            "month": month,
            "sku": sku,
            "calls": calls,
            "free_cap": free_cap,
            "remaining": max(0, free_cap - calls),
            "overage": max(0, calls - free_cap),
        }

    def mark_stale(self) -> int:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE jobs SET status='paused', updated_at=? WHERE status IN ('running','queued')",
                (_now(),))
        return cur.rowcount

    def delete_job(self, job_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
