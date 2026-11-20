"""Soft rules: each earns up to ``max_points`` toward the 0–100 fit score."""

from __future__ import annotations

from farmscout.domain.models import PropertyFacts, RuleOutcome
from farmscout.rules.base import Rule

# Existing uses that imply a permitted commercial / hospitality pathway.
HOSPITALITY_USES = {
    "winery", "tasting room", "event venue", "wedding venue", "restaurant", "retreat center",
    "bed and breakfast", "lodge", "inn", "cidery", "brewery", "distillery", "farm stand",
    "campground", "guest ranch",
}


def hospitality_uses(facts: PropertyFacts) -> list[str]:
    return [u for u in facts.existing_uses if u.lower() in HOSPITALITY_USES]


class CommercialPathwayRule(Rule):
    """Can this land legally host a restaurant/event/sauna business?"""

    rule_id = "commercial_pathway"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        uses = hospitality_uses(facts)
        if facts.zoning_class == "commercial":
            return self.passed(f"Zoning '{facts.zoning}' reads as commercial — venue/restaurant plausible")
        if uses:
            return self.passed(f"Existing use ({', '.join(uses)}) suggests permits already in place")
        if facts.zoning_class == "mixed":
            return self.partial(0.5, f"Zoning '{facts.zoning}' may allow events via conditional use")
        if facts.zoning_class in {"farm_only", "forest_only"}:
            return self.failed(f"Zoning '{facts.zoning}' is resource land — venue/restaurant hard to permit")
        if facts.zoning_class == "other":
            return self.unknown(f"Zoning '{facts.zoning}' not recognized — check county code")
        return self.unknown("Zoning not found — check county GIS for commercial/conditional uses")


class ExistingApprovedUseRule(Rule):
    """Existing permitted hospitality use. Not applicable to vacant land (zoning decides there)."""
    rule_id = "existing_approved_use"

    def applies(self, facts: PropertyFacts) -> bool:
        return not facts.is_land

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        uses = hospitality_uses(facts)
        if uses:
            return self.passed(f"Operating/permitted use: {', '.join(uses)}")
        return self.failed("No existing hospitality use mentioned")


class WaterSupplyRule(Rule):
    rule_id = "water_supply"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        if facts.has_water_rights:
            return self.passed("Irrigation water rights")
        if facts.has_well:
            return self.partial(0.6, "Well on site (no water rights mentioned)")
        if facts.has_water_rights is False and facts.has_well is False:
            return self.failed("No well or water rights")
        return self.unknown("Water rights / well not mentioned")


class PlungeWaterRule(Rule):
    """Natural water for a cold plunge next to the sauna."""

    rule_id = "plunge_water"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        if facts.water_features:
            return self.passed(f"Natural water: {', '.join(facts.water_features)}")
        return self.failed("No creek, river, pond or shoreline mentioned")


class MetroProximityRule(Rule):
    """Event guests and farm-stand customers: how far is the nearest city?"""

    rule_id = "metro_proximity"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        m, city = facts.drive_minutes_to_metro, facts.nearest_metro or "a city"
        if m is None:
            return self.unknown("Drive time to the nearest city unknown")
        if m <= 60:
            return self.passed(f"~{m} min to {city}")
        if m <= 90:
            return self.partial(0.7, f"~{m} min to {city}")
        if m <= 120:
            return self.partial(0.4, f"~{m} min to {city}")
        return self.failed(f"~{m} min to {city}: far for event guests")


class HomeProximityRule(Rule):
    """Favors places close to home (Seattle): full points within ``full_within`` minutes,
    sliding to zero at ``zero_at``."""

    rule_id = "home_proximity"

    def __init__(self, max_points: float, home_name: str = "Seattle",
                 full_within: int = 90, zero_at: int = 600) -> None:
        super().__init__(max_points)
        self._home, self._full, self._zero = home_name, full_within, zero_at

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        m = facts.drive_minutes_to_home
        if m is None:
            return self.unknown(f"Drive time to {self._home} unknown")
        hours = f"~{m / 60:.1f} h to {self._home}"
        if m <= self._full:
            return self.passed(hours)
        fraction = max(0.0, (self._zero - m) / (self._zero - self._full))
        if fraction == 0:
            return self.failed(f"{hours}: a long way from home")
        return self.partial(round(fraction, 2), hours)


class BuildingRule(Rule):
    """Rules about existing buildings. They don't apply to vacant land; build_readiness does."""

    def applies(self, facts: PropertyFacts) -> bool:
        return not facts.is_land


class ConvertibleBuildingsRule(BuildingRule):
    rule_id = "convertible_buildings"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        sqft = facts.largest_outbuilding_sqft
        if sqft is not None and sqft >= 1500:
            return self.passed(f"Large outbuilding (~{sqft:,} sq ft) for events or a kitchen")
        if facts.has_barn or (sqft and sqft > 0):
            return self.partial(0.5, "Barn/outbuilding present (size unknown or small)")
        if facts.has_barn is False:
            return self.failed("No barn or shop")
        return self.unknown("Outbuildings not described")


class CommercialKitchenRule(BuildingRule):
    rule_id = "commercial_kitchen"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        if facts.has_commercial_kitchen:
            return self.passed("Commercial kitchen")
        return self.failed("No commercial kitchen mentioned")


class ExtraDwellingRule(BuildingRule):
    rule_id = "extra_dwelling"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        if facts.dwellings is None:
            return self.unknown("Number of dwellings unclear")
        if facts.dwellings >= 2:
            return self.passed(f"{facts.dwellings} dwellings (staff/guest housing)")
        return self.failed("Single dwelling")


class AccessRule(Rule):
    rule_id = "access"

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        if facts.road_access == "paved":
            return self.passed("Paved road access")
        if facts.road_access == "gravel":
            return self.partial(0.6, "Gravel road access")
        if facts.road_access == "shared_private":
            return self.failed("Shared private road/easement — neighbors can contest traffic")
        return self.unknown("Road access not described")


class AcreageFitRule(Rule):
    """Full points inside the ideal acreage band; partial for small or very large parcels."""

    rule_id = "acreage_fit"

    def __init__(self, max_points: float, ideal_min: float, ideal_max: float) -> None:
        super().__init__(max_points)
        self._lo, self._hi = ideal_min, ideal_max

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        a = facts.acres
        if a is None:
            return self.unknown("Acreage unknown")
        if self._lo <= a <= self._hi:
            return self.passed(f"{a:g} acres is in the ideal {self._lo:g}–{self._hi:g} range")
        if a < self._lo:
            return self.partial(0.4, f"{a:g} acres is tight for farming plus events")
        return self.partial(0.6, f"{a:g} acres is more land to pay for and maintain")


class BuildReadinessRule(Rule):
    """Vacant land only: how ready is it to build on? Power, water, septic, and road access."""

    rule_id = "build_readiness"

    def applies(self, facts: PropertyFacts) -> bool:
        return facts.is_land

    def evaluate(self, facts: PropertyFacts) -> RuleOutcome:
        checks = {
            "power": facts.has_power,
            "water": True if (facts.has_well or facts.has_water_rights or facts.has_public_water)
                     else (False if facts.has_well is False and facts.has_public_water is False else None),
            "septic": None if facts.septic is None else facts.septic in {"existing", "approved", "perc_tested"},
            "road": None if facts.road_access is None else facts.road_access != "shared_private",
        }
        have = [k for k, v in checks.items() if v is True]
        missing = [k for k, v in checks.items() if v is False]
        unknown = [k for k, v in checks.items() if v is None]
        if len(unknown) == len(checks):
            return self.unknown("Vacant land: power, water, septic and access not described")
        reason = "Vacant land ready: " + (", ".join(have) or "nothing confirmed")
        if missing:
            reason += f"; missing {', '.join(missing)}"
        if unknown:
            reason += f"; check {', '.join(unknown)}"
        fraction = len(have) / len(checks)
        return self.passed(reason) if fraction == 1 else self.partial(round(fraction, 2), reason)
