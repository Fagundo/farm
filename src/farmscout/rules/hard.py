"""Hard filters: budget, geography, acreage."""

from __future__ import annotations

from farmscout.config.settings import HardFilters
from farmscout.domain.models import PropertyFacts, RuleOutcome
from farmscout.rules.base import HardRule


class PriceCapRule(HardRule):
    rule_id = "price_cap"

    def __init__(self, filters: HardFilters) -> None:
        super().__init__()
        self._f = filters

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        cap = self._f.max_price_usd
        if facts.price_usd is None:
            return self.unknown("Price not found — confirm it is under ${:,}".format(cap))
        if facts.price_usd <= cap:
            return self.passed(f"Price ${facts.price_usd:,} is within ${cap:,}")
        return self.failed(f"Price ${facts.price_usd:,} exceeds ${cap:,} cap")


class RegionRule(HardRule):
    rule_id = "region"

    def __init__(self, filters: HardFilters, counties_by_state: dict[str, tuple[str, ...]]) -> None:
        super().__init__()
        self._states = {s.upper() for s in filters.allowed_states}
        self._counties = {
            st.upper(): {c.lower() for c in cs} for st, cs in counties_by_state.items()
        }

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        state = (facts.state or "").upper() or None
        if state is None:
            return self.unknown("State not found — confirm WA/OR")
        if state not in self._states:
            return self.failed(f"State {state} is outside the search area")
        if facts.county is None:
            return self.unknown(f"County not found ({state}) — confirm it is in the target region")
        county = facts.county.lower().removesuffix(" county").strip()
        allowed = self._counties.get(state)
        if allowed is not None and county not in allowed:
            return self.failed(f"{facts.county} County, {state} is outside the target counties")
        return self.passed(f"{facts.county} County, {state} is in the target region")


class AcreageRule(HardRule):
    rule_id = "acreage"

    def __init__(self, filters: HardFilters) -> None:
        super().__init__()
        self._f = filters

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        lo, hi = self._f.min_acres, self._f.max_acres
        if facts.acres is None:
            return self.unknown(f"Acreage not found — target {lo:g}–{hi:g} acres")
        if lo <= facts.acres <= hi:
            return self.passed(f"{facts.acres:g} acres is within {lo:g}–{hi:g}")
        return self.failed(f"{facts.acres:g} acres is outside {lo:g}–{hi:g}")


class ListingStatusRule(HardRule):
    """Drops listings that research found sold or withdrawn; flags pending ones."""

    rule_id = "listing_status"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        status = (facts.listing_status or "").lower()
        if status in {"sold", "off_market"}:
            return self.failed(f"Listing is {status.replace('_', ' ')}")
        if status == "pending":
            return self.unknown("Sale pending — ask the agent for backup-offer status")
        if status == "active":
            return self.passed("Listing confirmed active")
        return self.unknown("Listing status not confirmed")


class HomeDistanceRule(HardRule):
    """Out of range when the estimated drive to home (Seattle) exceeds the configured maximum."""

    rule_id = "home_distance"

    def __init__(self, max_minutes: int | None, home_name: str = "Seattle") -> None:
        super().__init__()
        self._max, self._home = max_minutes, home_name

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        m = facts.drive_minutes_to_home
        if self._max is None:
            return self.passed("")
        if m is None:
            return self.unknown(f"Distance to {self._home} unknown")
        if m <= self._max:
            return self.passed(f"Within {self._max / 60:.0f} h of {self._home}")
        return self.failed(f"~{m / 60:.1f} h from {self._home} (limit {self._max / 60:.0f} h)")


class VacantLandRule(HardRule):
    """When vacant land is switched off in the config, only properties with existing buildings
    (farms, venues, vineyards, lodges...) stay in the running."""

    rule_id = "vacant_land"

    def __init__(self, include_land: bool) -> None:
        super().__init__()
        self._include = include_land

    def applies(self, facts: PropertyFacts) -> bool:
        return not self._include and facts.is_land

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        return self.failed("Vacant land: search is limited to existing farms, venues and vineyards")


class LandZoningRule(HardRule):
    """Vacant land must be zoned so a venue/restaurant/sauna business can be permitted. Farm- or
    forest-only land has no existing use to grandfather, so it's out."""

    rule_id = "land_zoning"

    def applies(self, facts: PropertyFacts) -> bool:
        return facts.is_land

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        z = facts.zoning_class
        if z in {"farm_only", "forest_only"}:
            return self.failed(f"Vacant land zoned '{facts.zoning}' (resource land): venue/restaurant/spa not permittable")
        if z == "commercial":
            return self.passed(f"Vacant land zoned '{facts.zoning}' for commercial use")
        if z == "mixed":
            return self.passed(f"Vacant land zoned '{facts.zoning}': events likely by conditional use")
        return self.unknown("Vacant land with zoning not confirmed: check the county zoning map")


class LandPriceRule(HardRule):
    """Vacant land must leave room in the budget to build."""

    rule_id = "land_price"

    def __init__(self, max_price_usd: int | None) -> None:
        super().__init__()
        self._max = max_price_usd

    def applies(self, facts: PropertyFacts) -> bool:
        return facts.is_land and self._max is not None

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        if facts.price_usd is None:
            return self.unknown("Land price not found")
        if facts.price_usd <= self._max:
            return self.passed(f"Land at ${facts.price_usd:,} leaves room to build")
        return self.failed(f"Land at ${facts.price_usd:,} is over the ${self._max:,} land cap (leaves too little to build)")
