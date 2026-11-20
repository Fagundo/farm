"""Judges, per business type, whether a property could legally host it."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from farmscout.business.uses import BusinessUse, BusinessUseCatalog
from farmscout.domain.models import PropertyFacts


class Fit(str, Enum):
    EXISTING = "existing"        # already operating / permitted on site
    LIKELY = "likely"            # zoning reads as allowing it outright
    CONDITIONAL = "conditional"  # probably needs a conditional-use permit
    LIMITED = "limited"          # resource land: only a capped/agritourism version
    UNLIKELY = "unlikely"
    UNKNOWN = "unknown"


FIT_CREDIT = {
    Fit.EXISTING: 1.0, Fit.LIKELY: 1.0, Fit.CONDITIONAL: 0.5,
    Fit.LIMITED: 0.0, Fit.UNLIKELY: 0.0, Fit.UNKNOWN: 0.0,
}


@dataclass(frozen=True)
class UseAssessment:
    use: BusinessUse
    fit: Fit
    reason: str

    def credit(self, catalog: BusinessUseCatalog) -> float:
        base = self.use.resource_zone_credit if self.fit is Fit.LIMITED else FIT_CREDIT[self.fit]
        return base * catalog.relative_weight(self.use)


class BusinessFitAssessor:
    def __init__(self, catalog: BusinessUseCatalog) -> None:
        self.catalog = catalog

    def assess(self, facts: PropertyFacts) -> list[UseAssessment]:
        return [self._assess_one(use, facts) for use in self.catalog]

    def fits(self, facts: PropertyFacts) -> dict[str, str]:
        """``{use key: fit}`` for storing on the facts and showing on the site."""
        return {a.use.key: a.fit.value for a in self.assess(facts)}

    def best(self, facts: PropertyFacts) -> tuple[UseAssessment, float]:
        scored = [(a, a.credit(self.catalog)) for a in self.assess(facts)]
        return max(scored, key=lambda pair: pair[1])

    @staticmethod
    def _assess_one(use: BusinessUse, facts: PropertyFacts) -> UseAssessment:
        if found := use.matching_uses(facts.existing_uses):
            return UseAssessment(use, Fit.EXISTING, f"existing {', '.join(found)}")
        if use.zoning_allows(facts.zoning):
            return UseAssessment(use, Fit.LIKELY, f"zone '{facts.zoning}' fits")
        cls = facts.zoning_class
        if cls == "commercial":
            return UseAssessment(use, Fit.LIKELY, f"commercial zone '{facts.zoning}'")
        if cls == "mixed":
            return UseAssessment(use, Fit.CONDITIONAL, f"'{facts.zoning}' likely needs a conditional-use permit")
        if cls in {"farm_only", "forest_only"}:
            if use.resource_zone_credit > 0:
                return UseAssessment(use, Fit.LIMITED, f"resource zone '{facts.zoning}': limited/agritourism version only")
            return UseAssessment(use, Fit.UNLIKELY, f"resource zone '{facts.zoning}'")
        if cls == "other":
            return UseAssessment(use, Fit.UNKNOWN, f"zone '{facts.zoning}' not recognized")
        return UseAssessment(use, Fit.UNKNOWN, "zoning not found")
