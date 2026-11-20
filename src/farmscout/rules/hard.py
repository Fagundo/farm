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
