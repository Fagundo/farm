"""Enrichers derive extra facts after extraction (zoning class, drive time, ...)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import replace

from farmscout.domain.models import PropertyFacts
from farmscout.zoning.classifier import ZoningClassifier


class Enricher(ABC):
    @abstractmethod
    def enrich(self, facts: PropertyFacts) -> PropertyFacts: ...


class ZoningClassEnricher(Enricher):
    def __init__(self, classifier: ZoningClassifier) -> None:
        self._c = classifier

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        return replace(facts, zoning_class=self._c.classify(facts.zoning))


class DriveTimeEnricher(Enricher):
    """Estimates drive minutes to the nearest metro from a (state, county) lookup table.

    Keyed by state because county names repeat across states (Lincoln, Douglas, Columbia...).
    """

    def __init__(self, minutes: dict[str, dict[str, int]]) -> None:
        self._table = {
            st.upper(): {c.lower(): m for c, m in counties.items()} for st, counties in minutes.items()
        }

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        if facts.drive_minutes_to_metro is not None or not facts.county or not facts.state:
            return facts
        county = facts.county.lower().removesuffix(" county").strip()
        minutes = self._table.get(facts.state.upper(), {}).get(county)
        return replace(facts, drive_minutes_to_metro=minutes)


class EnrichmentChain(Enricher):
    def __init__(self, enrichers: Sequence[Enricher]) -> None:
        self._enrichers = list(enrichers)

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        for e in self._enrichers:
            facts = e.enrich(facts)
        return facts
