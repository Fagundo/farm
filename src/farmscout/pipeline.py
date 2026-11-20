"""The scouting pipeline: discover → dedupe → fetch → extract → enrich → evaluate → store → report.

Every stage is injected, so any stage can be swapped or faked in tests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from farmscout.domain.models import Evaluation, PropertyFacts, RawListing
from farmscout.enrichment.enrichers import Enricher
from farmscout.extraction.base import FactExtractor
from farmscout.fetching.fetcher import PageFetcher
from farmscout.reporting.reporters import Reporter
from farmscout.rules.engine import RuleEngine
from farmscout.sources.base import ListingSource
from farmscout.storage.repository import CandidateRepository, normalize_url

log = logging.getLogger("farmscout")


@dataclass
class RunSummary:
    discovered: int = 0
    skipped_seen: int = 0
    evaluated: int = 0
    disqualified: int = 0
    new: int = 0
    reports: list[Path] = field(default_factory=list)


class ScoutPipeline:
    def __init__(
        self,
        source: ListingSource,
        fetcher: PageFetcher,
        extractor: FactExtractor,
        enricher: Enricher,
        engine: RuleEngine,
        repository: CandidateRepository,
        reporters: Sequence[Reporter],
    ) -> None:
        self._source = source
        self._fetcher = fetcher
        self._extractor = extractor
        self._enricher = enricher
        self._engine = engine
        self._repo = repository
        self._reporters = list(reporters)

    def evaluate_facts(self, facts: PropertyFacts) -> Evaluation:
        """Score facts gathered elsewhere (e.g. manual research), skipping fetch/extract."""
        return self._engine.evaluate(self._enricher.enrich(facts))

    def import_facts(self, items: Iterable[PropertyFacts]) -> RunSummary:
        summary, new_urls = RunSummary(), set()
        for facts in items:
            ev = self.evaluate_facts(facts)
            summary.discovered += 1
            summary.evaluated += 1
            summary.disqualified += ev.disqualified
            if self._repo.save(ev):
                summary.new += 1
                new_urls.add(ev.facts.url)
        summary.reports = self.report(new_urls)
        return summary

    def evaluate(self, listing: RawListing) -> Evaluation:
        text = self._fetcher.fetch_text(listing.url)
        if listing.prefilled is not None:
            facts = listing.prefilled
            if text is not None:  # page readable: fill gaps (zoning, water, buildings) from it
                facts = facts.merged_with(self._extractor.extract(listing, text))
        elif text is None and not (listing.title or listing.snippet):
            raise LookupError("page unavailable and no search snippet to work from")
        else:
            facts = self._extractor.extract(listing, text)
        return self._engine.evaluate(self._enricher.enrich(facts))

    def run(self, *, refresh: bool = False, limit: int | None = None) -> RunSummary:
        summary = RunSummary()
        new_urls: set[str] = set()
        for listing in self._unique(self._source.discover()):
            summary.discovered += 1
            if not refresh and self._repo.has(listing.url):
                summary.skipped_seen += 1
                continue
            if limit is not None and summary.evaluated >= limit:
                break
            try:
                ev = self.evaluate(listing)
            except Exception as exc:  # noqa: BLE001 — one bad listing must not stop the run
                log.warning("evaluate failed for %s: %s", listing.url, exc)
                continue
            summary.evaluated += 1
            summary.disqualified += ev.disqualified
            if self._repo.save(ev):
                summary.new += 1
                new_urls.add(ev.facts.url)
            log.info("%5.1f %s %s", ev.score, "DQ" if ev.disqualified else "  ", listing.url)
        summary.reports = self.report(new_urls)
        return summary

    def rescore(self) -> int:
        """Re-evaluate every stored property against the current rules; return how many changed."""
        changed = 0
        for c in self._repo.all():
            ev = self.evaluate_facts(c.evaluation.facts)
            if ev.score != c.evaluation.score or ev.disqualified != c.evaluation.disqualified:
                self._repo.save(ev)
                changed += 1
        return changed

    def report(self, new_urls: set[str] | None = None, new_within_days: int = 7) -> list[Path]:
        """Write every report. Without explicit ``new_urls``, "new" means first seen within N days."""
        self.rescore()
        stored = self._repo.all()
        if new_urls is None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=new_within_days)).isoformat()
            new_urls = {c.evaluation.facts.url for c in stored if c.first_seen >= cutoff}
        evaluations = [c.evaluation for c in stored]
        return [r.write(evaluations, new_urls) for r in self._reporters]

    @staticmethod
    def _unique(listings: Iterable[RawListing]) -> Iterable[RawListing]:
        seen: set[str] = set()
        for l in listings:
            key = normalize_url(l.url)
            if key not in seen:
                seen.add(key)
                yield l
