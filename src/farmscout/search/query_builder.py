"""Builds search queries from the criteria: property types x places, weighted toward home."""

from __future__ import annotations

import itertools
import random
from collections.abc import Callable, Sequence

from farmscout.config.settings import SearchPlace, SearchSettings

#: Minutes from home to a place, or None if unknown.
DistanceFn = Callable[[SearchPlace], int | None]


def proximity_weight(minutes: int | None, half_at: int = 240) -> float:
    """1.0 next door, 0.5 at ``half_at`` minutes (4 h), ~0.15 at 9 h. Unknown places get 0.3."""
    if minutes is None:
        return 0.3
    return 1.0 / (1.0 + (minutes / half_at) ** 2)


class QueryBuilder:
    def __init__(self, settings: SearchSettings, max_price_usd: int, seed: int | None = None,
                 distance: DistanceFn | None = None) -> None:
        self._s = settings
        self._price = max_price_usd
        self._rng = random.Random(seed)
        self._distance = distance or (lambda place: None)

    def build(self) -> list[str]:
        """Queries for open web search (brokerages, land sites, venue/winery brokers)."""
        return self._combine(self._s.property_types, self._s.max_queries)

    def build_portal(self) -> list[str]:
        """Queries for search restricted to Zillow/Redfin/Realtor.com."""
        cap = self._s.max_portal_queries or self._s.max_queries
        return self._combine(self._s.portal_property_types, cap)

    def _combine(self, types: Sequence[str], cap: int) -> list[str]:
        price = (f"under ${self._price // 1000:,}k" if self._price < 1_000_000
                 else f"under ${self._price / 1e6:g} million")
        weights = {p: proximity_weight(self._distance(p)) for p in self._s.places}
        combos = list(itertools.product(types, self._s.places))
        # Weighted sampling without replacement (Efraimidis-Spirakis): near places come up more
        # often, far ones still appear now and then, and every run is a different slice.
        keyed = sorted(combos, key=lambda c: self._rng.random() ** (1.0 / weights[c[1]]), reverse=True)
        return [self._phrase(t, p.name, price) for t, p in keyed[:cap]]

    @staticmethod
    def _phrase(ptype: str, place: str, price: str) -> str:
        return f"{ptype} {place} {price}" if "for sale" in ptype else f"{ptype} for sale {place} {price}"
