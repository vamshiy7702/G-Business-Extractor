import asyncio

import httpx

from leadx.adapters.google_places import GooglePlacesAdapter, QuotaExceeded, parse_google_place
from leadx.geo import Tile


def test_parse_google_place():
    p = parse_google_place({
        "id": "abc",
        "displayName": {"text": "Acme Dental"},
        "formattedAddress": "1 Main St, Bengaluru, Karnataka 560001, India",
        "location": {"latitude": 12.1, "longitude": 77.1},
        "primaryType": "dentist",
        "nationalPhoneNumber": "+91 80 1111 2222",
        "websiteUri": "https://acme.example",
        "rating": 4.5,
        "addressComponents": [
            {"longText": "Bengaluru", "types": ["locality"]},
            {"longText": "Karnataka", "types": ["administrative_area_level_1"]},
            {"longText": "560001", "types": ["postal_code"]},
            {"longText": "India", "types": ["country"]},
        ],
    })
    assert p.name == "Acme Dental"
    assert p.city == "Bengaluru" and p.state == "Karnataka" and p.postal_code == "560001"
    assert p.rating == 4.5 and p.source_place_id == "abc"


def test_google_quote():
    adapter = GooglePlacesAdapter(httpx.AsyncClient(), api_key="x")
    quote = adapter.estimate_cost(tiles_total=4, results_per_tile=50, max_places=200, calls_this_month=0)
    asyncio.run(adapter.client.aclose())
    assert quote.estimated_calls == 12


def test_google_quota_guard_stops_before_request():
    seen = []
    async def handler(request: httpx.Request):
        seen.append(1)
        return httpx.Response(200, json={"places": []})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GooglePlacesAdapter(client, api_key="x", quota_guard=lambda: (_ for _ in ()).throw(QuotaExceeded("cap")))
    async def run():
        try:
            await adapter.search("dentist", Tile(12, 77, 12.1, 77.1), 10)
        finally:
            await client.aclose()
    try:
        asyncio.run(run())
    except QuotaExceeded:
        pass
    else:
        raise AssertionError("QuotaExceeded not raised")
    assert not seen
