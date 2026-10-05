from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, fields
from typing import Optional


def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


@dataclass
class PlaceDTO:
    source: str
    source_place_id: str
    name: str
    category: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    rating: Optional[float] = None
    email_status: str = "pending"

    @property
    def dedup_key(self) -> str:
        if self.source_place_id:
            return f"{self.source}:{self.source_place_id}"
        raw = "|".join([_norm(self.name), _norm(self.phone), _norm(self.address)])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @property
    def soft_key(self) -> str | None:
        tail = _norm(self.phone) or _norm(self.address)
        return f"{_norm(self.name)}|{tail}" if tail else None

    def as_row(self) -> dict:
        return asdict(self)

    @classmethod
    def columns(cls) -> list[str]:
        return [f.name for f in fields(cls)]


def dedup(places: list[PlaceDTO]) -> list[PlaceDTO]:
    """Deduplicate by source id, then by name + phone/address."""
    seen_ids: set[str] = set()
    seen_soft: set[str] = set()
    out: list[PlaceDTO] = []
    for place in places:
        if place.dedup_key in seen_ids:
            continue
        soft = place.soft_key
        if soft and soft in seen_soft:
            continue
        seen_ids.add(place.dedup_key)
        if soft:
            seen_soft.add(soft)
        out.append(place)
    return out
