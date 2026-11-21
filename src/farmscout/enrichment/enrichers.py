"""Enrichers derive extra facts after extraction (zoning class, drive time, ...)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import replace

from farmscout.business import BusinessFitAssessor, SettingDetector
from farmscout.domain.models import PropertyFacts
from farmscout.geo.drive_time import CountyTable, DriveTimeModel, Place
from farmscout.zoning.classifier import ZoningClassifier


class Enricher(ABC):
    @abstractmethod
    def enrich(self, facts: PropertyFacts) -> PropertyFacts: ...


class ZoningClassEnricher(Enricher):
    def __init__(self, classifier: ZoningClassifier) -> None:
        self._c = classifier

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        return replace(facts, zoning_class=self._c.classify(facts.zoning))


class CountyFromCoordinatesEnricher(Enricher):
    """Fills a missing county with the nearest listed county seat in the same state.

    Approximate near county lines, but enough for the region and drive-time rules.
    """

    def __init__(self, counties: CountyTable) -> None:
        self._counties = counties

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        if facts.county or facts.latitude is None or facts.longitude is None or not facts.state:
            return facts
        nearest = self._counties.nearest(facts.state, facts.latitude, facts.longitude)
        return replace(facts, county=nearest.name) if nearest else facts


class DriveTimeEnricher(Enricher):
    """Estimates drive minutes to home (Seattle) and to the nearest metro.

    Uses the property's own coordinates when known, else its county's (by state + county, since
    county names repeat across states). Always recomputed, so config changes take effect.
    """

    def __init__(self, counties: CountyTable, home: Place, metros: Sequence[Place],
                 model: DriveTimeModel) -> None:
        self._counties = counties
        self._home = home
        self._metros = list(metros)
        self._model = model

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        county = self._counties.get(facts.state, facts.county)
        if facts.latitude is not None and facts.longitude is not None:
            lat, lon = facts.latitude, facts.longitude
        elif county is not None:
            lat, lon = county.lat, county.lon
        else:
            return replace(facts, drive_minutes_to_home=None, drive_minutes_to_metro=None, nearest_metro=None)
        kw = {"road_factor": county.road_factor, "adjust_min": county.adjust_min} if county else {}
        to_home = self._model.minutes(lat, lon, self._home, **kw)
        metro, to_metro = min(((m, self._model.minutes(lat, lon, m, **kw)) for m in self._metros),
                              key=lambda t: t[1])
        return replace(facts, drive_minutes_to_home=to_home, drive_minutes_to_metro=to_metro,
                       nearest_metro=metro.name)


class EnrichmentChain(Enricher):
    def __init__(self, enrichers: Sequence[Enricher]) -> None:
        self._enrichers = list(enrichers)

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        for e in self._enrichers:
            facts = e.enrich(facts)
        return facts


class SettingEnricher(Enricher):
    """Fills ``setting`` (secluded/roadside) from the title, summary and research notes when the
    extractor left it blank. Re-run on every rescore, so older records pick it up too."""

    def __init__(self, detector: SettingDetector) -> None:
        self._d = detector

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        if facts.setting:
            return facts
        found = self._d.detect(facts.title, facts.summary, facts.research_notes)
        return replace(facts, setting=found) if found else facts


class BusinessFitEnricher(Enricher):
    """Records which business types (venue, food, wellness) the property could host.
    Must run after ZoningClassEnricher."""

    def __init__(self, assessor: BusinessFitAssessor) -> None:
        self._a = assessor

    def enrich(self, facts: PropertyFacts) -> PropertyFacts:
        return replace(facts, business_fits=self._a.fits(facts))
