"""Builds search queries from the criteria (property types x places)."""

from __future__ import annotations

import itertools
import random

from farmscout.config.settings import SearchSettings


class QueryBuilder:
    def __init__(self, settings: SearchSettings, max_price_usd: int, seed: int | None = None) -> None:
        self._s = settings
        self._price = max_price_usd
        self._rng = random.Random(seed)

    def build(self) -> list[str]:
        """Queries for open web search (brokerages, land sites, venue/winery brokers)."""
        return self._combine(self._s.property_types, self._s.max_queries)

    def build_portal(self) -> list[str]:
        """Queries for search restricted to Zillow/Redfin/Realtor.com."""
        cap = self._s.max_portal_queries or self._s.max_queries
        return self._combine(self._s.portal_property_types, cap)

    def _combine(self, types, cap: int) -> list[str]:
        price = f"under ${self._price // 1000:,}k" if self._price < 1_000_000 else f"under ${self._price / 1e6:g} million"
        combos = [f"{t} for sale {p} {price}" if "for sale" not in t else f"{t} {p} {price}"
                  for t, p in itertools.product(types, self._s.places)]
        # Shuffle so a capped run still covers a spread of types and places.
        self._rng.shuffle(combos)
        return combos[:cap]
