from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx

from ..geo import Tile
from ..models import PlaceDTO
from ..categories import filters_for
from .base import Quote

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CATEGORY_KEYS = ("amenity", "shop", "office", "healthcare", "tourism", "craft", "leisure")
MIN_SPLIT_DEG = 0.02          # never split a tile below ~2 km
MAX_SPLIT_DEPTH = 3


class OverpassTimeout(RuntimeError):
    """Overpass answered HTTP 200 but reported a runtime error (timeout / out of memory)."""


def build_query(keyword: str, tile: Tile, limit: int, timeout: int = 60) -> str:
    filters, _mode = filters_for(keyword)
    if not filters:
        raise ValueError(f"Category {keyword!r} has no searchable characters")
    body = "\n".join(f'  nwr[{f}]["name"]({tile.bbox});' for f in filters)   # named only: unnamed objects are dropped later and would waste the limit
    return f"[out:json][timeout:{timeout}];\n(\n{body}\n);\nout center tags {limit};"


def _first(tags: dict, *keys: str) -> str:
    for key in keys:
        value = tags.get(key)
        if value:
            return str(value).strip()
    return ""


def parse_element(el: dict[str, Any]) -> Optional[PlaceDTO]:
    tags = el.get("tags") or {}
    name = tags.get("name") or tags.get("name:en") or tags.get("brand")
    if not name:
        return None
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lng = el.get("lon") or (el.get("center") or {}).get("lon")
    street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
    address = ", ".join(x for x in (street, tags.get("addr:suburb"), tags.get("addr:city"),
                                    tags.get("addr:state"), tags.get("addr:postcode")) if x)
    if not address:
        address = _first(tags, "addr:full")
    category = ""
    for key in CATEGORY_KEYS:
        if tags.get(key):
            category = str(tags[key]).replace("_", " ")
            break
    try:
        lat_f = float(lat) if lat is not None else None
        lng_f = float(lng) if lng is not None else None
    except (TypeError, ValueError):
        lat_f = lng_f = None
    return PlaceDTO(
        source="osm",
        source_place_id=f"{el.get('type', 'node')}/{el.get('id')}",
        name=str(name).strip(), category=category, address=address,
        city=_first(tags, "addr:city", "addr:town", "addr:village"),
        state=_first(tags, "addr:state"), postal_code=_first(tags, "addr:postcode"),
        country=_first(tags, "addr:country"),
        phone=_first(tags, "phone", "contact:phone", "contact:mobile"),
        email=_first(tags, "email", "contact:email"),
        website=_first(tags, "website", "contact:website", "url"),
        lat=lat_f, lng=lng_f, rating=None,
        email_status="found" if tags.get("email") or tags.get("contact:email") else "pending",
    )


class OsmOverpassAdapter:
    name = "osm"
    _FREE_CAP = 10**9

    def __init__(self, client: httpx.AsyncClient, retries: int = 3, delay: float = 1.5,
                 overpass_url: str = OVERPASS_URL):
        self.client = client
        self.retries = retries
        self.delay = delay
        self.overpass_url = overpass_url

    async def _run(self, query: str) -> list[dict]:
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                r = await self.client.post(self.overpass_url, data={"data": query})
                if r.status_code in (429, 502, 503, 504):
                    raise httpx.HTTPStatusError(f"Overpass busy (HTTP {r.status_code})", request=r.request, response=r)
                r.raise_for_status()
                payload = r.json()
                remark = str(payload.get("remark") or "")
                if "runtime error" in remark.lower():
                    # Overpass reports timeouts / out-of-memory with HTTP 200 and an EMPTY result.
                    # The old code treated that as "no businesses here", silently losing the tile.
                    raise OverpassTimeout(remark[:200])
                await asyncio.sleep(self.delay)
                return payload.get("elements", [])
            except OverpassTimeout:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
                if attempt < self.retries:
                    await asyncio.sleep(5 * attempt)
        raise last or RuntimeError("Overpass request failed")

    async def search(self, keyword: str, tile: Tile, limit: int, _depth: int = 0) -> list[PlaceDTO]:
        query = build_query(keyword, tile, min(limit, 1000))
        try:
            elements = await self._run(query)
        except OverpassTimeout:
            span = max(tile.north - tile.south, tile.east - tile.west)
            if _depth >= MAX_SPLIT_DEPTH or span / 2 < MIN_SPLIT_DEG:
                raise
            # Too much data for one query: search the four quadrants instead.
            mid_lat, mid_lng = (tile.south + tile.north) / 2, (tile.west + tile.east) / 2
            quads = [Tile(tile.south, tile.west, mid_lat, mid_lng), Tile(tile.south, mid_lng, mid_lat, tile.east),
                     Tile(mid_lat, tile.west, tile.north, mid_lng), Tile(mid_lat, mid_lng, tile.north, tile.east)]
            out: list[PlaceDTO] = []
            for q in quads:
                out += await self.search(keyword, q, limit - len(out), _depth + 1)
                if len(out) >= limit:
                    break
            return out[:limit]
        return [p for p in (parse_element(e) for e in elements) if p]

    def estimate_cost(self, *, tiles_total: int, results_per_tile: int,
                      max_places: int, calls_this_month: int = 0) -> Quote:
        return Quote("osm-overpass", 0, self._FREE_CAP, calls_this_month, 0.0,
                     self._FREE_CAP, None)
