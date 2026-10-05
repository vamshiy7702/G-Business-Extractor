from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Location(BaseModel):
    city: str = Field(default="All cities", min_length=1, max_length=100)
    state: str = Field(default="All states", min_length=1, max_length=100)
    country: str = Field(default="All countries", min_length=1, max_length=60, description="2-letter code/name or All countries")
    postal_code: str = Field(default="All zip codes", min_length=1, max_length=30)
    # Optional ids from the cascading location pickers (names above stay the human-readable values).
    country_code: str = Field(default="", max_length=3)
    state_id: Optional[int] = None
    city_id: Optional[int] = None


class JobOptions(BaseModel):
    max_places: int = Field(default=200, ge=1, le=5000)
    results_per_tile: int = Field(default=200, ge=1, le=1000)
    tile_deg: float = Field(default=0.05, ge=0.01, le=5.0)
    extract_emails: bool = False
    threads: int = Field(default=4, ge=1, le=10)


class CreateJobRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=100)
    location: Location
    source: Literal["osm", "google"] = "osm"
    options: JobOptions = Field(default_factory=JobOptions)

    @field_validator("keyword")
    @classmethod
    def clean_keyword(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("keyword must not be blank")
        return value


class BulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


class PlaceDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=5000)


class JobOut(BaseModel):
    id: int
    keyword: str
    city: str
    state: str
    country: str
    postal_code: str
    source: str
    status: str
    tiles_total: int
    tiles_done: int
    places_found: int
    max_places: int
    extract_emails: bool
    progress: float
    error: Optional[str] = None
    created_at: str
    updated_at: str
    finished_at: Optional[str] = None
    estimate_calls: Optional[int] = None
    estimate_cost_usd: Optional[float] = None
    quota_free_cap: Optional[int] = None
    quota_calls_this_month: Optional[int] = None
    quota_remaining: Optional[int] = None


class PlaceOut(BaseModel):
    id: int
    source: str
    source_place_id: str
    name: str
    category: str
    address: str
    city: str
    state: str
    postal_code: str
    country: str
    phone: str
    email: str
    website: str
    lat: float | None
    lng: float | None
    rating: float | None
    email_status: str


class QuoteOut(BaseModel):
    source: str
    tiles_total: int
    estimated_calls: int
    estimated_cost_usd: float
    free_cap: int | None = None
    calls_this_month: int | None = None
    remaining_free_calls: int | None = None
    sku: str | None = None
    warning: str | None = None


def job_out(row, quote: Optional[dict] = None) -> JobOut:
    d = dict(row)
    total = max(1, d["tiles_total"] or 1)
    if d["status"] == "done":
        progress = 100.0
    else:
        progress = round(100 * d["tiles_done"] / total, 1)
    options = {}
    try:
        import json
        options = json.loads(d.get("options_json") or "{}")
    except Exception:
        options = {}
    d["postal_code"] = d.get("postal_code", "")
    d["extract_emails"] = bool(options.get("extract_emails", False))
    d["progress"] = progress
    for key, value in (quote or {}).items():
        d[key] = value
    allowed = set(JobOut.model_fields)
    return JobOut(**{k: d[k] for k in allowed if k in d})
