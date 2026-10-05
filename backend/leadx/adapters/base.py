from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..geo import Tile
from ..models import PlaceDTO


@dataclass(frozen=True)
class Quote:
    sku: str
    estimated_calls: int
    free_cap: int
    calls_this_month: int
    estimated_cost_usd: float
    remaining_free_calls: int
    warning: str | None = None


class SourceAdapter(Protocol):
    name: str

    async def search(self, keyword: str, tile: Tile, limit: int) -> list[PlaceDTO]:
        ...

    def estimate_cost(self, *, tiles_total: int, results_per_tile: int,
                      max_places: int, calls_this_month: int = 0) -> Quote:
        ...
