"""Red-flag rules that subtract points."""

from __future__ import annotations

from farmscout.domain.models import PropertyFacts, RuleOutcome
from farmscout.rules.base import PenaltyRule
from farmscout.business.uses import DEFAULT_BUSINESS_USES, BusinessUseCatalog
from farmscout.rules.soft import hospitality_uses


class FloodplainPenalty(PenaltyRule):
    rule_id = "floodplain"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        if facts.in_floodplain:
            return self.triggered("In or near a floodplain")
        if facts.in_floodplain is None and facts.water_features:
            return self.unknown("Has water frontage — check FEMA flood maps")
        return self.clear()


class HoaPenalty(PenaltyRule):
    rule_id = "hoa"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        if facts.has_hoa:
            return self.triggered("HOA / CC&Rs may bar commercial use")
        return self.clear()


class SharedRoadPenalty(PenaltyRule):
    rule_id = "shared_private_road"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        if facts.road_access == "shared_private":
            return self.triggered("Shared private road")
        return self.clear()


class FarmOnlyNoExistingUsePenalty(PenaltyRule):
    rule_id = "farm_only_no_existing_use"

    def __init__(self, max_points: float, catalog: BusinessUseCatalog | None = None) -> None:
        super().__init__(max_points)
        self._catalog = catalog or BusinessUseCatalog(DEFAULT_BUSINESS_USES)

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        if facts.zoning_class in {"farm_only", "forest_only"} and not hospitality_uses(facts, self._catalog):
            return self.triggered(f"Resource zoning ('{facts.zoning}') with no grandfathered venue, food or spa use")
        return self.clear()
