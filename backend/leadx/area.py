"""Turn a selected Country/State/City/ZIP into a search bounding box.

Order: ZIP centroid (from the location database, no network) -> Nominatim (administrative area)
-> offline fallbacks computed from the location database, so a geocoder hiccup no longer
leaves a task that can never produce data."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import httpx

from .geo import box_around, is_all
from .locations import LocationsDB, LocationsUnavailable
from .schemas import Location

ZIP_HALF_DEG = 0.02       # ~2.2 km each side of the ZIP centroid
CITY_HALF_DEG = 0.12      # ~13 km each side of the city centre (fallback only)

Geocoder = Callable[..., Awaitable[tuple[float, float, float, float]]]


async def _call(geocoder: Geocoder, client, loc: Location, cc: str):
    try:
        return await geocoder(client, loc.city, loc.state, loc.country, loc.postal_code, cc)
    except TypeError:
        try:
            return await geocoder(client, loc.city, loc.state, loc.country, loc.postal_code)
        except TypeError:
            return await geocoder(client, loc.city, loc.state, loc.country)


async def locate(client: httpx.AsyncClient, locdb: LocationsDB, geocoder: Geocoder,
                 loc: Location) -> tuple[tuple[float, float, float, float], str]:
    """Returns (south, west, north, east) and a short note saying how the area was determined."""
    if is_all(loc.country):
        raise ValueError("All countries cannot be searched as one area. Select a country "
                         "(and optionally a state, city and ZIP code).")
    cc, state_row, city_row = (loc.country_code or "").upper(), None, None
    try:
        if locdb.available:
            cc = cc or (locdb.country_code(loc.country) or "")
            if cc and not is_all(loc.state):
                state_row = locdb.find_state(cc, loc.state)
            if not is_all(loc.city):
                city_row = locdb.city_row(loc.city_id) if loc.city_id else None
                if city_row is not None and cc and city_row["country"] != cc:
                    city_row = None                      # stale/mismatched id: fall back to the name lookup
                if city_row is None and state_row is not None:
                    city_row = locdb.find_city(state_row["id"], loc.city)
    except LocationsUnavailable:
        pass

    # 1) a selected ZIP code: use its centroid from the dataset (works offline)
    if city_row is not None and not is_all(loc.postal_code):
        pt = locdb.zip_point(city_row["id"], loc.postal_code.strip())
        if pt:
            return box_around(pt[0], pt[1], ZIP_HALF_DEG), "zip-centroid"

    # 2) administrative area from Nominatim
    error: Optional[Exception] = None
    try:
        return await _call(geocoder, client, loc, cc), "nominatim"
    except (ValueError, httpx.HTTPError) as exc:
        error = exc

    # 3) offline fallbacks from the location database
    if locdb.available:
        if city_row is not None and city_row["lat"] is not None:
            return box_around(city_row["lat"], city_row["lng"], CITY_HALF_DEG), "dataset-city-centre"
        if is_all(loc.city) and state_row is not None:
            bb = locdb.state_bbox(state_row["id"])
            if bb:
                return bb, "dataset-state-extent"
        if is_all(loc.city) and is_all(loc.state) and cc:
            bb = locdb.country_bbox(cc)
            if bb:
                return bb, "dataset-country-extent"
    raise error  # type: ignore[misc]
