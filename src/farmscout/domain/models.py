"""Core domain types. Pure data: no I/O, no dependencies on other layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class RawListing:
    """A lead discovered by a source, before any page fetch or extraction."""

    url: str
    title: str = ""
    snippet: str = ""
    source: str = ""
    # Structured sources (CSV exports, listing APIs) hand over facts they already know.
    # These win over anything extracted from the page.
    prefilled: "PropertyFacts | None" = field(default=None, compare=False)


@dataclass
class PropertyFacts:
    """Structured facts about a property. ``None`` always means *unknown*."""

    url: str
    title: str = ""
    source: str = ""
    price_usd: int | None = None
    acres: float | None = None
    state: str | None = None
    county: str | None = None
    city: str | None = None
    zoning: str | None = None
    zoning_class: str | None = None
    existing_uses: list[str] = field(default_factory=list)
    has_water_rights: bool | None = None
    has_well: bool | None = None
    water_features: list[str] = field(default_factory=list)
    has_commercial_kitchen: bool | None = None
    dwellings: int | None = None
    has_barn: bool | None = None
    largest_outbuilding_sqft: int | None = None
    road_access: str | None = None  # "paved" | "gravel" | "shared_private"
    property_type: str | None = None  # "land" (vacant) | "improved" (has a home or buildings)
    has_power: bool | None = None     # power on site or at the road
    has_public_water: bool | None = None
    septic: str | None = None         # "existing" | "approved" | "perc_tested" | "none"
    setting: str | None = None        # "secluded" | "roadside" (relaxation favors secluded)
    business_fits: dict[str, str] = field(default_factory=dict)  # use key -> Fit, set by enrichment
    in_floodplain: bool | None = None
    has_hoa: bool | None = None
    drive_minutes_to_metro: int | None = None
    drive_minutes_to_home: int | None = None   # to Seattle (config [home])
    nearest_metro: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    summary: str = ""
    # Filled by the research step.
    listing_status: str | None = None  # "active" | "pending" | "sold" | "off_market"
    canonical_url: str | None = None  # a working listing page, when ``url`` is stale or generic
    research_notes: str = ""
    research_sources: list[str] = field(default_factory=list)
    researched_at: str | None = None
    status_checked_at: str | None = None
    # Filled by the link check.
    link_status: str | None = None  # "ok" | "broken" | "wrong_property" | "blocked" | "unreachable"
    link_checked_at: str | None = None

    @property
    def link(self) -> str:
        return self.canonical_url or self.url

    @property
    def is_land(self) -> bool:
        """Vacant land: stated as such, or no dwellings and no buildings."""
        if self.property_type:
            return self.property_type == "land"
        return self.dwellings == 0 and self.has_barn is False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PropertyFacts":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def merged_with(self, fallback: "PropertyFacts") -> "PropertyFacts":
        """Return a copy where unknown/empty fields are filled from ``fallback``."""
        merged = {}
        for f in fields(self):
            mine, theirs = getattr(self, f.name), getattr(fallback, f.name)
            empty = mine is None or mine == "" or mine == []
            if isinstance(mine, list) and isinstance(theirs, list):
                merged[f.name] = sorted(set(mine) | set(theirs))
            else:
                merged[f.name] = theirs if empty else mine
        return PropertyFacts(**merged)


class Status(str, Enum):
    NOT_APPLICABLE = "n/a"
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    status: Status
    points: float
    max_points: float
    reason: str
    hard: bool = False
    penalty: bool = False


@dataclass
class Evaluation:
    facts: PropertyFacts
    outcomes: list[RuleOutcome]
    score: float
    disqualified: bool

    @property
    def strengths(self) -> list[str]:
        return [o.reason for o in self.outcomes if o.status is Status.PASS and not o.penalty and not o.hard]

    @property
    def red_flags(self) -> list[str]:
        return [o.reason for o in self.outcomes if (o.penalty and o.points < 0) or (o.hard and o.status is Status.FAIL)]

    @property
    def to_verify(self) -> list[str]:
        return [o.reason for o in self.outcomes if o.status is Status.UNKNOWN]
