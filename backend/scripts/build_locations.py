#!/usr/bin/env python3
"""Build backend/leadx/data/locations.db: Country -> State -> City -> ZIP code lists.

Sources (both free, redistributable with attribution):
  * Countries / states / cities : dr5hn/countries-states-cities-database  (ODbL 1.0)
        https://github.com/dr5hn/countries-states-cities-database
  * Postal codes                : GeoNames postal codes, as converted by zauberware  (CC BY 4.0)
        https://github.com/zauberware/postal-codes-json-xml-csv

Usage (needs internet, ~120 MB download, takes about a minute):
    python scripts/build_locations.py
Offline, from files you already downloaded:
    python scripts/build_locations.py --csc csc.json --postal-dir postal_by_country/

HOW A ZIP CODE IS TIED TO A CITY (kept deliberately conservative so that a city never
receives another city's ZIP codes):
  1. A postal row qualifies only if the normalised city name is EXACTLY EQUAL (no prefix/
     suffix/"contains" matching) to the row's settlement name (`place`), or for the few
     countries listed in COUNTRY_FIELDS to the district/municipality field as well.
  2. If both the city and the row have coordinates, the row must lie within MAX_KM of
     the city (this separates homonyms such as the many "Springfield"s).
  3. Rows without coordinates are NEVER accepted (an earlier draft accepted them for unique
     city names and wrongly attached ZIPs from other German cities to Munich/Berlin).
Cities that get no ZIP codes simply show "All zip codes" in the app (nothing is invented).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sqlite3
import sys
import unicodedata
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CSC_URL = "https://raw.githubusercontent.com/dr5hn/countries-states-cities-database/master/json/countries+states+cities.json"
POSTAL_URL = "https://codeload.github.com/zauberware/postal-codes-json-xml-csv/zip/refs/heads/master"

MAX_KM = 50.0
# Which GeoNames columns may hold the *city* name, per country (default: only `place`).
COUNTRY_FIELDS: dict[str, tuple[str, ...]] = {
    "IN": ("place", "province"),     # GeoNames `place` is a post office; `province` is the district (= city for metros)
    # DE deliberately uses `place` only: GeoNames' German file also lists company-specific ZIPs whose
    # `community` is the city (e.g. 10875 = a Daimler office in Stuttgart); matching on community pulls them in.
}
COUNTRY_MAX_KM = {"IN": 80.0}
NOISE = {"stadtkreis", "landkreis", "kreisfreie", "stadt", "landeshauptstadt", "kreis", "city", "district",
         "municipality", "metropolitan", "county", "borough"}
# Well-known English <-> local city names (GeoNames uses the local name). Only used as extra lookups.
ALIASES = {
    "munich": ["munchen"], "cologne": ["koln"], "nuremberg": ["nurnberg"], "vienna": ["wien"],
    "rome": ["roma"], "milan": ["milano"], "florence": ["firenze"], "venice": ["venezia"],
    "naples": ["napoli"], "turin": ["torino"], "genoa": ["genova"], "prague": ["praha"],
    "warsaw": ["warszawa"], "lisbon": ["lisboa"], "seville": ["sevilla"], "brussels": ["bruxelles", "brussel"],
    "copenhagen": ["kobenhavn"], "athens": ["athina"], "moscow": ["moskva"], "the hague": ["s gravenhage", "den haag"],
    "geneva": ["geneve", "genf"], "zurich": ["zurich"], "bern": ["berne"], "gothenburg": ["goteborg"],
    "krakow": ["krakow"], "bucharest": ["bucuresti"], "belgrade": ["beograd"], "sofia": ["sofiya"],
}


def norm(s: str | None, strip_noise: bool = False) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = s.split()
    if strip_noise:
        toks = [t for t in toks if t not in NOISE]
    return " ".join(toks)


def hav_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def fetch(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    print(f"downloading {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "leadx-location-builder"})
    with urllib.request.urlopen(req, timeout=300) as r, dest.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    return dest


def read_postal_zip(path: Path) -> dict[str, list[dict]]:
    """country -> rows, from the repository archive (data/XX.zip each holding zipcodes.xx.csv)."""
    out: dict[str, list[dict]] = {}
    with zipfile.ZipFile(path) as outer:
        for name in outer.namelist():
            m = re.search(r"/data/([A-Z]{2})\.zip$", name)
            if not m:
                continue
            with zipfile.ZipFile(io.BytesIO(outer.read(name))) as inner:
                csvs = [n for n in inner.namelist() if n.lower().endswith(".csv")]
                if csvs:
                    text = inner.read(csvs[0]).decode("utf-8", errors="replace")
                    out[m.group(1)] = list(csv.DictReader(io.StringIO(text)))
    return out


def read_postal_dir(path: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in sorted(path.glob("*/zipcodes.*.csv")) + sorted(path.glob("zipcodes.*.csv")):
        cc = p.stem.split(".")[-1].upper()
        out[cc] = list(csv.DictReader(p.open(encoding="utf-8")))
    return out


def build(csc_path: Path, postal: dict[str, list[dict]], out_path: Path) -> dict:
    data = json.loads(csc_path.read_text(encoding="utf-8"))
    if out_path.exists():
        out_path.unlink()
    db = sqlite3.connect(out_path)
    db.executescript("""
      CREATE TABLE countries (iso2 TEXT PRIMARY KEY, name TEXT NOT NULL, iso3 TEXT, region TEXT,
                              postal_code_format TEXT, has_zip INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE states (id INTEGER PRIMARY KEY, country TEXT NOT NULL, name TEXT NOT NULL, code TEXT, type TEXT,
                           lat REAL, lng REAL);
      CREATE TABLE cities (id INTEGER PRIMARY KEY, state_id INTEGER NOT NULL, country TEXT NOT NULL, name TEXT NOT NULL,
                           lat REAL, lng REAL);
      CREATE TABLE zips (city_id INTEGER NOT NULL, code TEXT NOT NULL, label TEXT, lat REAL, lng REAL,
                         PRIMARY KEY (city_id, code));
      CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
      CREATE INDEX idx_states_country ON states(country);
      CREATE INDEX idx_cities_state ON cities(state_id);
      CREATE INDEX idx_cities_country ON cities(country);
    """)
    stats = defaultdict(int)
    for co in data:
        cc = co["iso2"]
        db.execute("INSERT INTO countries VALUES (?,?,?,?,?,?)",
                   (cc, co["name"], co.get("iso3"), co.get("region"), co.get("postal_code_format"),
                    1 if cc in postal else 0))
        stats["countries"] += 1
        for st in co.get("states", []):
            def f(v):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            db.execute("INSERT INTO states VALUES (?,?,?,?,?,?,?)",
                       (st["id"], cc, st["name"], st.get("iso2"), st.get("type"), f(st.get("latitude")), f(st.get("longitude"))))
            stats["states"] += 1
            for ci in st.get("cities", []):
                db.execute("INSERT INTO cities VALUES (?,?,?,?,?,?)",
                           (ci["id"], st["id"], cc, ci["name"], f(ci.get("latitude")), f(ci.get("longitude"))))
                stats["cities"] += 1

    # ---- ZIP matching -----------------------------------------------------------------------
    cities = db.execute("SELECT id, country, name, lat, lng FROM cities").fetchall()

    index: dict[str, dict[str, list[tuple]]] = {}
    for cc, rows in postal.items():
        fields = COUNTRY_FIELDS.get(cc, ("place",))
        idx: dict[str, list[tuple]] = defaultdict(list)
        for r in rows:
            code = (r.get("zipcode") or "").strip()
            if not code:
                continue
            try:
                la, lo = float(r["latitude"]), float(r["longitude"])
            except (KeyError, TypeError, ValueError):
                la = lo = None
            keys = set()
            for fld in fields:
                for part in (r.get(fld) or "").split(",") if fld != "place" else [r.get(fld) or ""]:
                    k = norm(part, strip_noise=(fld != "place"))
                    if k:
                        keys.add(k)
            for k in keys:
                idx[k].append((code, la, lo, (r.get("place") or "").strip()))
        index[cc] = idx

    rows_out, with_zip, eligible = [], 0, 0
    for cid, cc, name, clat, clng in cities:
        idx = index.get(cc)
        if not idx:
            continue
        eligible += 1
        n = norm(name)
        cands = list(idx.get(n, []))
        for alias in ALIASES.get(n, []):
            cands += idx.get(alias, [])
        if not cands:
            continue
        limit = COUNTRY_MAX_KM.get(cc, MAX_KM)
        found: dict[str, dict] = {}
        for code, la, lo, place in cands:
            if la is None or lo is None or clat is None or clng is None:
                continue                    # cannot verify the row belongs to THIS city
            if hav_km(clat, clng, la, lo) > limit:
                continue
            e = found.setdefault(code, {"lat": la, "lng": lo, "places": []})
            if place and place not in e["places"] and len(e["places"]) < 3:
                e["places"].append(place)
        if found:
            with_zip += 1
            for code, e in found.items():
                rows_out.append((cid, code, ", ".join(e["places"])[:80], e["lat"], e["lng"]))
    db.executemany("INSERT OR IGNORE INTO zips VALUES (?,?,?,?,?)", rows_out)
    stats["zip_links"] = len(rows_out)
    stats["cities_in_countries_with_postal_data"] = eligible
    stats["cities_with_zip"] = with_zip

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": json.dumps({"cities": CSC_URL, "postal": POSTAL_URL}),
        "licenses": "dr5hn countries-states-cities-database: ODbL 1.0; GeoNames postal codes: CC BY 4.0",
        "stats": json.dumps(stats),
        "zip_rule": f"exact name match + coordinates required + <= {MAX_KM} km (IN {COUNTRY_MAX_KM['IN']} km); fields {COUNTRY_FIELDS}",
    }
    db.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
    db.commit()
    db.execute("VACUUM")
    db.close()
    return dict(stats)


def main() -> int:
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csc", help="local countries+states+cities.json (skips download)")
    ap.add_argument("--postal-zip", help="local zip of the postal-codes repository (skips download)")
    ap.add_argument("--postal-dir", help="directory of extracted zipcodes.XX.csv files")
    ap.add_argument("--cache", default=str(here / "scripts" / ".cache"))
    ap.add_argument("--out", default=str(here / "leadx" / "data" / "locations.db"))
    a = ap.parse_args()
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    csc = Path(a.csc) if a.csc else fetch(CSC_URL, cache / "csc.json")
    if a.postal_dir:
        postal = read_postal_dir(Path(a.postal_dir))
    else:
        postal = read_postal_zip(Path(a.postal_zip) if a.postal_zip else fetch(POSTAL_URL, cache / "postal.zip"))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    print(f"postal data for {len(postal)} countries; building {a.out}", flush=True)
    stats = build(csc, postal, Path(a.out))
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
