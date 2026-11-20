"""Rule engine: runs hard gates, soft scores and penalties into one Evaluation."""

from __future__ import annotations

from collections.abc import Sequence

from farmscout.business import BusinessFitAssessor
from farmscout.config.settings import Settings
from farmscout.domain.models import Evaluation, PropertyFacts, Status
from farmscout.rules import hard, penalties, soft
from farmscout.rules.base import Rule


class RuleEngine:
    def __init__(self, rules: Sequence[Rule], keep_unknowns: bool = True) -> None:
        self._rules = list(rules)
        self._keep_unknowns = keep_unknowns

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    def evaluate(self, facts: PropertyFacts) -> Evaluation:
        outcomes = [r.evaluate(facts) if r.applies(facts) else r.not_applicable() for r in self._rules]
        disqualified = any(
            o.hard and (o.status is Status.FAIL or (o.status is Status.UNKNOWN and not self._keep_unknowns))
            for o in outcomes
        )
        max_total = sum(o.max_points for o in outcomes if not o.hard and not o.penalty) or 1.0
        raw = sum(o.points for o in outcomes if not o.hard)
        score = max(0.0, min(100.0, 100.0 * raw / max_total))
        return Evaluation(facts=facts, outcomes=outcomes, score=round(score, 1), disqualified=disqualified)


# Registry: config weight key -> soft rule class. Adding a rule = add a class + a weight.
SOFT_RULES: dict[str, type[Rule]] = {
    "business_pathway": soft.BusinessPathwayRule,  # built with the business-use catalog
    "seclusion": soft.SeclusionRule,
    "existing_approved_use": soft.ExistingApprovedUseRule,
    "water_supply": soft.WaterSupplyRule,
    "plunge_water": soft.PlungeWaterRule,
    "metro_proximity": soft.MetroProximityRule,
    "convertible_buildings": soft.ConvertibleBuildingsRule,
    "commercial_kitchen": soft.CommercialKitchenRule,
    "extra_dwelling": soft.ExtraDwellingRule,
    "access": soft.AccessRule,
    "build_readiness": soft.BuildReadinessRule,
    "acreage_fit": soft.AcreageFitRule,  # built with the ideal range in build_engine
    "home_proximity": soft.HomeProximityRule,  # built with the home name in build_engine
}

PENALTY_RULES: dict[str, type[Rule]] = {
    "floodplain": penalties.FloodplainPenalty,
    "hoa": penalties.HoaPenalty,
    "shared_private_road": penalties.SharedRoadPenalty,
    "farm_only_no_existing_use": penalties.FarmOnlyNoExistingUsePenalty,
}


def build_engine(settings: Settings) -> RuleEngine:
    hf = settings.hard_filters
    rules: list[Rule] = [
        hard.PriceCapRule(hf),
        hard.RegionRule(hf, settings.counties_by_state),
        hard.AcreageRule(hf),
        hard.ListingStatusRule(),
        hard.HomeDistanceRule(hf.max_drive_minutes_to_home, settings.home.name),
        hard.LandZoningRule(),
        hard.LandPriceRule(settings.land_max_price_usd),
    ]
    catalog = settings.business_uses
    for key, weight in settings.weights.items():
        if key == "business_pathway":
            rules.append(soft.BusinessPathwayRule(weight, BusinessFitAssessor(catalog)))
            continue
        if key == "existing_approved_use":
            rules.append(soft.ExistingApprovedUseRule(weight, catalog))
            continue
        if key == "acreage_fit":
            rules.append(soft.AcreageFitRule(weight, *settings.acreage_ideal))
            continue
        if key == "home_proximity":
            rules.append(soft.HomeProximityRule(weight, settings.home.name))
            continue
        if key not in SOFT_RULES:
            raise ValueError(f"Unknown weight '{key}' in config; known: {sorted(SOFT_RULES)}")
        rules.append(SOFT_RULES[key](weight))
    for key, amount in settings.penalties.items():
        if key not in PENALTY_RULES:
            raise ValueError(f"Unknown penalty '{key}' in config; known: {sorted(PENALTY_RULES)}")
        if key == "farm_only_no_existing_use":
            rules.append(penalties.FarmOnlyNoExistingUsePenalty(amount, catalog))
            continue
        rules.append(PENALTY_RULES[key](amount))
    return RuleEngine(rules, keep_unknowns=hf.keep_unknowns)
