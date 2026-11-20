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
    """Estimates drive minutes to Seattle/Portland from a county lookup table."""

    def __init__(self, minutes_by_county: dict[str, int]) -> None:
        self._table = {k.lower(): v for k, v in minutes_by_county.items()}

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        if facts.drive_minutes_to_metro is not None or not facts.county:
            return facts
        minutes = self._table.get(facts.county.lower().removesuffix(" county").strip())
        return replace(facts, drive_minutes_to_metro=minutes)


class EnrichmentChain(Enricher):
    def __init__(self, enrichers: Sequence[Enricher]) -> None:
        self._enrichers = list(enrichers)

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        for e in self._enrichers:
            facts = e.enrich(facts)
        return facts
