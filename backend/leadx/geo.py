from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from urllib.parse import quote_plus

import httpx

from .config import settings

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
MAX_TILES = 400
_GEO_LOCK = asyncio.Lock()
_GEO_LAST_REQUEST = 0.0


@dataclass(frozen=True)
class Tile:
    south: float
    west: float
    north: float
    east: float

    @property
    def bbox(self) -> str:
        return f"{self.south:.6f},{self.west:.6f},{self.north:.6f},{self.east:.6f}"


def tile_grid(south: float, west: float, north: float, east: float,
              max_tile_deg: float = 0.05) -> tuple[int, int]:
    rows = max(1, math.ceil((north - south) / max_tile_deg - 1e-9))
    cols = max(1, math.ceil((east - west) / max_tile_deg - 1e-9))
    return rows, cols


def count_tiles(south: float, west: float, north: float, east: float,
                max_tile_deg: float = 0.05) -> int:
    rows, cols = tile_grid(south, west, north, east, max_tile_deg)
    return rows * cols


def make_tiles(south: float, west: float, north: float, east: float,
               max_tile_deg: float = 0.05) -> list[Tile]:
    rows, cols = tile_grid(south, west, north, east, max_tile_deg)
    dlat = (north - south) / rows
    dlng = (east - west) / cols
    return [
        Tile(south + r * dlat, west + c * dlng,
             south + (r + 1) * dlat, west + (c + 1) * dlng)
        for r in range(rows) for c in range(cols)
    ]


ALL_LOCATION_TOKENS = {
    "all", "all countries", "all states", "all cities", "all zip codes", "all zips", "*"
}


def is_all(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() in ALL_LOCATION_TOKENS


def build_geocode_query(city: str = "", state: str = "", country: str = "", postal_code: str = "") -> str:
    """Build a bounded Nominatim query from hierarchical location filters.

    The most specific non-ALL level is used. ZIP codes are included only when
    a concrete city is also supplied, avoiding an overly broad postal-only query.
    """
    if is_all(country):
        raise ValueError(
            "All countries cannot be geocoded as one bounded OSM search area. "
            "Select a country before starting an OSM extraction."
        )

    city_is_all = is_all(city)
    state_is_all = is_all(state)
    zip_is_all = is_all(postal_code)

    parts: list[str] = []
    if not city_is_all:
        parts.append(city.strip())
        if not state_is_all:
            parts.append(state.strip())
        if not zip_is_all:
            parts.append(postal_code.strip())
        if not is_all(country):
            parts.append(country.strip())
    elif not state_is_all:
        parts.append(state.strip())
        if not is_all(country):
            parts.append(country.strip())
    else:
        parts.append(country.strip())

    return ", ".join(x for x in parts if x)


def adaptive_tile_deg(bbox: tuple[float, float, float, float], requested: float, max_tiles: int) -> float:
    """Increase tile size for broad country/state scopes so the safety cap is usable.

    The requested size is preserved for small areas. For larger areas the value is
    increased only enough to keep the tile count within max_tiles.
    """
    if max_tiles < 1:
        return requested
    south, west, north, east = bbox
    span_lat = max(0.0, north - south)
    span_lng = max(0.0, east - west)
    target = max(requested, span_lat / math.sqrt(max_tiles), span_lng / math.sqrt(max_tiles))
    # Keep the effective value within the JobOptions upper bound. If a region
    # is still too large at this maximum, the API will reject it rather than
    # creating an unbounded/slow extraction.
    return min(target, 5.0)


async def _nominatim(client: httpx.AsyncClient, params: dict) -> list:
    """One rate-limited Nominatim call (public server: max 1 request/second, identifiable User-Agent)."""
    global _GEO_LAST_REQUEST
    async with _GEO_LOCK:
        now = asyncio.get_running_loop().time()
        wait_for = settings.nominatim_min_interval - (now - _GEO_LAST_REQUEST)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        headers = {
            "User-Agent": settings.nominatim_user_agent,
            "Referer": settings.nominatim_referer,
            "Accept": "application/json",
        }
        if settings.contact_email:
            headers["User-Agent"] = f"{settings.nominatim_user_agent} (contact: {settings.contact_email})"
        r = await client.get(NOMINATIM_URL, params=params, headers=headers)
        _GEO_LAST_REQUEST = asyncio.get_running_loop().time()
    if r.status_code == 403:
        raise httpx.HTTPStatusError(
            "Nominatim returned 403 Forbidden. Set a descriptive NOMINATIM_USER_AGENT and a real "
            "CONTACT_EMAIL in backend/.env and restart the backend.", request=r.request, response=r)
    r.raise_for_status()
    return r.json()


def _bbox_of(item: dict) -> tuple[float, float, float, float]:
    bbox = item.get("boundingbox")
    if not bbox or len(bbox) != 4:
        raise ValueError("Location has no bounding box")
    south, north, west, east = (float(x) for x in bbox)     # Nominatim order: S, N, W, E
    return south, west, north, east


async def geocode_bbox(client: httpx.AsyncClient, city: str, state: str = "", country: str = "",
                       postal_code: str = "", country_code: str = "") -> tuple[float, float, float, float]:
    """Bounding box of the most specific selected level.

    Uses Nominatim's *structured* search (city=/state=/country=/postalcode=) first, which is far more
    reliable than gluing names into one free-text string, then falls back to the free-text query."""
    q = build_geocode_query(city, state, country, postal_code)      # raises for "All countries"
    cc = (country_code or (country.strip() if len(country.strip()) == 2 else "")).lower()
    structured: dict = {"format": "json", "limit": 1}
    if not is_all(city):
        structured["city"] = city.strip()
    if not is_all(state):
        structured["state"] = state.strip()
    if not is_all(postal_code):
        structured["postalcode"] = postal_code.strip()
    country_name = country.strip()
    if country_name and not is_all(country_name) and len(country_name) != 2:
        # Always send the country NAME when we have one: with only `countrycodes` a country-level search
        # ("All states / All cities") would reach Nominatim with no search term at all.
        structured["country"] = country_name
    if cc:
        structured["countrycodes"] = cc
    has_term = any(k in structured for k in ("city", "state", "postalcode", "country"))
    data = await _nominatim(client, structured) if has_term else []
    if not data:
        free: dict = {"q": q, "format": "json", "limit": 1}
        if cc:
            free["countrycodes"] = cc
        data = await _nominatim(client, free)
    if not data:
        raise ValueError(f"Could not find location: {q}")
    return _bbox_of(data[0])


def box_around(lat: float, lng: float, half_deg: float) -> tuple[float, float, float, float]:
    return lat - half_deg, lng - half_deg, lat + half_deg, lng + half_deg
