from __future__ import annotations

import math
from typing import Any

import httpx

from ..config import settings
from ..geo import Tile
from ..models import PlaceDTO
from .base import Quote

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


class QuotaExceeded(RuntimeError):
    pass


class GoogleApiError(RuntimeError):
    pass


def _google_error(r: httpx.Response) -> GoogleApiError:
    """Google explains most failures (invalid key, API not enabled, billing) in the JSON body."""
    try:
        err = r.json().get("error", {})
        detail = err.get("message") or err.get("status") or ""
    except Exception:
        detail = ""
    return GoogleApiError(f"Google Places API error {r.status_code}: {detail or r.reason_phrase}")


TEXT_SEARCH_FIELDS = ",".join([
    "places.id", "places.displayName", "places.formattedAddress", "places.location",
    "places.primaryType", "places.nationalPhoneNumber", "places.internationalPhoneNumber",
    "places.websiteUri", "places.rating", "places.addressComponents", "nextPageToken",
])


def _component(components: list[dict[str, Any]], *types: str) -> str:
    wanted = set(types)
    for comp in components or []:
        if wanted.intersection(comp.get("types") or []):
            return str(comp.get("longText") or comp.get("shortText") or "")
    return ""


def parse_google_place(place: dict[str, Any]) -> PlaceDTO:
    display = place.get("displayName") or {}
    components = place.get("addressComponents") or []
    location = place.get("location") or {}
    place_id = str(place.get("id") or place.get("name", "").replace("places/", ""))
    category = str(place.get("primaryTypeDisplayName", {}).get("text") or place.get("primaryType") or "")
    return PlaceDTO(
        source="google",
        source_place_id=place_id,
        name=str(display.get("text") or "Unnamed business").strip(),
        category=category.replace("_", " "),
        address=str(place.get("formattedAddress") or ""),
        city=_component(components, "locality", "postal_town", "administrative_area_level_2"),
        state=_component(components, "administrative_area_level_1"),
        postal_code=_component(components, "postal_code"),
        country=_component(components, "country"),
        phone=str(place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber") or ""),
        website=str(place.get("websiteUri") or ""),
        lat=float(location["latitude"]) if "latitude" in location else None,
        lng=float(location["longitude"]) if "longitude" in location else None,
        rating=float(place["rating"]) if place.get("rating") is not None else None,
        email="",
        email_status="pending",
    )


class GooglePlacesAdapter:
    name = "google"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None,
                 text_search_url: str = TEXT_SEARCH_URL, max_pages: int = 3, quota_guard=None):
        self.client = client
        self.api_key = api_key or settings.google_places_api_key
        self.text_search_url = text_search_url
        self.max_pages = max_pages
        self.quota_guard = quota_guard

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY is not configured")
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": TEXT_SEARCH_FIELDS,
        }

    async def search(self, keyword: str, tile: Tile, limit: int) -> list[PlaceDTO]:
        headers = self._headers()
        limit = max(1, min(limit, 60))
        page_size = min(20, limit)
        out: list[PlaceDTO] = []
        page_token: str | None = None
        for _ in range(self.max_pages):
            body: dict[str, Any] = {
                "textQuery": keyword.strip(),
                "pageSize": page_size,
                "locationRestriction": {
                    "rectangle": {
                        "low": {"latitude": tile.south, "longitude": tile.west},
                        "high": {"latitude": tile.north, "longitude": tile.east},
                    }
                },
            }
            if page_token:
                body["pageToken"] = page_token
            if self.quota_guard:
                self.quota_guard()
            r = await self.client.post(self.text_search_url, json=body, headers=headers)
            if r.status_code >= 400:
                raise _google_error(r)
            payload = r.json()
            for place in payload.get("places") or []:
                out.append(parse_google_place(place))
                if len(out) >= limit:
                    return out[:limit]
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return out[:limit]

    def estimate_cost(self, *, tiles_total: int, results_per_tile: int,
                      max_places: int, calls_this_month: int = 0) -> Quote:
        effective_per_tile = min(results_per_tile, 60, max_places)
        calls_per_tile = max(1, math.ceil(effective_per_tile / 20))
        estimated_calls = tiles_total * calls_per_tile
        free_cap = settings.google_text_search_free_cap
        remaining = max(0, free_cap - calls_this_month)
        billable_after_free = max(0, calls_this_month + estimated_calls - free_cap)
        cost = (billable_after_free / 1000.0) * settings.google_text_search_price_per_1000
        warning = None
        if estimated_calls > remaining:
            warning = (f"Estimated usage exceeds the configured free cap by "
                       f"{estimated_calls - remaining} calls.")
        return Quote("places-text-search-pro", estimated_calls, free_cap,
                     calls_this_month, round(cost, 4), remaining, warning)
