"""Read-only access to the Country -> State -> City -> ZIP database (data/locations.db).

Build or refresh it with:  python scripts/build_locations.py
Data: dr5hn/countries-states-cities-database (ODbL 1.0) + GeoNames postal codes (CC BY 4.0).
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Optional

from .config import settings


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


class LocationsUnavailable(RuntimeError):
    pass


class LocationsDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or settings.locations_db)
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def available(self) -> bool:
        return self.path.is_file()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self.available:
                raise LocationsUnavailable(
                    f"Location database not found at {self.path}. Run: python scripts/build_locations.py")
            c = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, check_same_thread=False)
            c.row_factory = sqlite3.Row
            self._conn = c
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ---- lists for the cascading dropdowns ------------------------------------------------
    def countries(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT c.iso2 AS code, c.name, c.has_zip, "
            "(SELECT COUNT(*) FROM states s WHERE s.country=c.iso2) AS state_count "
            "FROM countries c ORDER BY c.name").fetchall()
        return [{"code": r["code"], "name": r["name"], "has_zip": bool(r["has_zip"]),
                 "state_count": r["state_count"]} for r in rows]

    def states(self, country_code: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, name, code, type FROM states WHERE country=? ORDER BY name",
            (country_code.upper(),)).fetchall()
        return [dict(r) for r in rows]

    def cities(self, state_id: int, q: str = "", limit: int = 5000) -> list[dict]:
        sql, args = "SELECT id, name, lat, lng FROM cities WHERE state_id=?", [state_id]
        if q:
            sql += " AND name LIKE ?"
            args.append(f"%{q}%")
        sql += " ORDER BY name LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def zips(self, city_id: int, q: str = "") -> list[dict]:
        sql, args = "SELECT code, label, lat, lng FROM zips WHERE city_id=?", [city_id]
        if q:
            sql += " AND (code LIKE ? OR label LIKE ?)"
            args += [f"{q}%", f"%{q}%"]
        sql += " ORDER BY code"
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def meta(self) -> dict:
        out = {r["key"]: r["value"] for r in self.conn.execute("SELECT key, value FROM meta")}
        for k in ("sources", "stats"):
            if k in out:
                try:
                    out[k] = json.loads(out[k])
                except ValueError:
                    pass
        return out

    # ---- lookups used when starting a task -------------------------------------------------
    def country_code(self, value: str) -> Optional[str]:
        v = (value or "").strip()
        if not v:
            return None
        row = self.conn.execute("SELECT iso2 FROM countries WHERE iso2=? COLLATE NOCASE OR iso3=? COLLATE NOCASE",
                                (v, v)).fetchone()
        if row:
            return row["iso2"]
        for r in self.conn.execute("SELECT iso2, name FROM countries"):
            if _fold(r["name"]) == _fold(v):
                return r["iso2"]
        return None

    def find_state(self, country_code: str, name: str) -> Optional[sqlite3.Row]:
        for r in self.conn.execute("SELECT * FROM states WHERE country=?", (country_code,)):
            if _fold(r["name"]) == _fold(name):
                return r
        return None

    def find_city(self, state_id: int, name: str) -> Optional[sqlite3.Row]:
        for r in self.conn.execute("SELECT * FROM cities WHERE state_id=?", (state_id,)):
            if _fold(r["name"]) == _fold(name):
                return r
        return None

    def city_row(self, city_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM cities WHERE id=?", (city_id,)).fetchone()

    def zip_point(self, city_id: int, code: str) -> Optional[tuple[float, float]]:
        r = self.conn.execute("SELECT lat, lng FROM zips WHERE city_id=? AND code=?", (city_id, code)).fetchone()
        return (r["lat"], r["lng"]) if r and r["lat"] is not None and r["lng"] is not None else None

    def _bbox(self, where: str, arg, pad: float) -> Optional[tuple[float, float, float, float]]:
        r = self.conn.execute(
            f"SELECT MIN(lat) a, MIN(lng) b, MAX(lat) c, MAX(lng) d, COUNT(*) n FROM cities "
            f"WHERE {where} AND lat IS NOT NULL AND lng IS NOT NULL", (arg,)).fetchone()
        if not r or not r["n"]:
            return None
        return (r["a"] - pad, r["b"] - pad, r["c"] + pad, r["d"] + pad)

    def state_bbox(self, state_id: int, pad: float = 0.1):
        return self._bbox("state_id=?", state_id, pad)

    def country_bbox(self, country_code: str, pad: float = 0.1):
        return self._bbox("country=?", country_code, pad)
