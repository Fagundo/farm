"""Business types the property could host, loaded from ``[[business_uses]]`` in the config."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class BusinessUse:
    """One kind of business, e.g. an event venue, a restaurant or a spa with sauna.

    ``existing_uses``: operating uses that show this business is (or was) permitted on site.
    ``zoning_patterns``: zone names that allow this business even when the generic zoning class
    would not say so (e.g. "resort" or "recreation" zones for a spa).
    ``resource_zone_credit``: partial credit on farm/forest-only land, where some counties allow a
    limited version (e.g. a capped number of agritourism events).
    ``weight``: relative priority; equal weights mean whichever business fits best counts.
    """

    key: str
    label: str
    existing_uses: frozenset[str]
    zoning_patterns: tuple[str, ...] = ()
    resource_zone_credit: float = 0.0
    weight: float = 1.0

    def zoning_allows(self, zoning: str | None) -> bool:
        return bool(zoning) and any(re.search(p, zoning, re.I) for p in self.zoning_patterns)

    def matching_uses(self, existing: Iterable[str]) -> list[str]:
        return [u for u in existing if u.lower() in self.existing_uses]

    @classmethod
    def from_mapping(cls, raw: Mapping) -> "BusinessUse":
        return cls(
            key=raw["key"],
            label=raw.get("label", raw["key"]),
            existing_uses=frozenset(u.lower() for u in raw.get("existing_uses", [])),
            zoning_patterns=tuple(raw.get("zoning_patterns", [])),
            resource_zone_credit=float(raw.get("resource_zone_credit", 0.0)),
            weight=float(raw.get("weight", 1.0)),
        )


class BusinessUseCatalog:
    """The configured business types, in priority order."""

    def __init__(self, uses: Iterable[BusinessUse]) -> None:
        self._uses = tuple(uses)
        if not self._uses:
            raise ValueError("At least one [[business_uses]] entry is required")
        self._max_weight = max(u.weight for u in self._uses) or 1.0

    def __iter__(self):
        return iter(self._uses)

    def __len__(self) -> int:
        return len(self._uses)

    def get(self, key: str) -> BusinessUse | None:
        return next((u for u in self._uses if u.key == key), None)

    def relative_weight(self, use: BusinessUse) -> float:
        return use.weight / self._max_weight

    @property
    def all_existing_uses(self) -> frozenset[str]:
        """Every existing use that signals a permitted hospitality business of any type."""
        return frozenset().union(*(u.existing_uses for u in self._uses))

    def hospitality_uses(self, existing: Iterable[str]) -> list[str]:
        known = self.all_existing_uses
        return [u for u in existing if u.lower() in known]


# Used when the config has no [[business_uses]] (e.g. in tests); the config is the place to tune.
DEFAULT_BUSINESS_USES = (
    BusinessUse("venue", "Event venue", frozenset({
        "event venue", "wedding venue", "retreat center", "guest ranch", "campground", "glamping",
        "winery", "lodge"}), ("resort", "recreation", "tourist"), resource_zone_credit=0.25),
    BusinessUse("food", "Restaurant / farm-to-table", frozenset({
        "restaurant", "cafe", "winery", "tasting room", "cidery", "brewery", "distillery",
        "farm stand", "bed and breakfast", "inn", "lodge"}), ("tourist", "rural village", "resort")),
    BusinessUse("wellness", "Spa / sauna", frozenset({
        "spa", "bathhouse", "hot springs", "retreat center", "lodge", "inn", "bed and breakfast",
        "glamping", "guest ranch"}), ("resort", "recreation", "tourist")),
)
