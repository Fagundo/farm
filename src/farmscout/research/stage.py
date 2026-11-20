"""The research stage: pick candidates worth researching, research them, re-score, save."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from farmscout.domain.models import Evaluation
from farmscout.enrichment.enrichers import Enricher
from farmscout.research.base import PropertyResearcher
from farmscout.rules.engine import RuleEngine
from farmscout.storage.repository import CandidateRepository

log = logging.getLogger("farmscout")


@dataclass(frozen=True)
class ResearchPolicy:
    top_n: int = 20                 # research the best-scoring N candidates...
    max_age_days: int = 14          # ...that haven't been researched in this many days
    include_disqualified: bool = False


@dataclass
class ResearchSummary:
    considered: int = 0
    researched: int = 0
    changed_status: int = 0
    score_changes: list[tuple[str, float, float]] = None  # (url, before, after)

    def __post_init__(self) -> None:
        self.score_changes = self.score_changes or []


class ResearchStage:
    def __init__(
        self,
        researcher: PropertyResearcher,
        enricher: Enricher,
        engine: RuleEngine,
        repository: CandidateRepository,
        policy: ResearchPolicy = ResearchPolicy(),
        selector: Callable[[Evaluation], bool] | None = None,
    ) -> None:
        self._researcher = researcher
        self._enricher = enricher
        self._engine = engine
        self._repo = repository
        self._policy = policy
        self._selector = selector

    def _due(self, ev: Evaluation) -> bool:
        if self._selector is not None:
            return self._selector(ev)
        if ev.disqualified and not self._policy.include_disqualified:
            return False
        last = ev.facts.researched_at
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._policy.max_age_days)
        return last is None or last < cutoff.isoformat()

    def run(self) -> ResearchSummary:
        summary = ResearchSummary()
        queue = sorted((c.evaluation for c in self._repo.all()), key=lambda e: e.score, reverse=True)
        queue = [e for e in queue if self._due(e)][: self._policy.top_n]
        for ev in queue:
            summary.considered += 1
            try:
                result = self._researcher.research(ev.facts, ev.to_verify)
            except Exception as exc:  # noqa: BLE001 — one failure must not stop the stage
                log.warning("research failed for %s: %s", ev.facts.url, exc)
                continue
            if result is None:
                continue
            facts = self._enricher.enrich(result.apply_to(ev.facts))
            new = self._engine.evaluate(facts)
            self._repo.save(new)
            summary.researched += 1
            summary.changed_status += facts.listing_status != ev.facts.listing_status
            if new.score != ev.score or new.disqualified != ev.disqualified:
                summary.score_changes.append((facts.url, ev.score, -1 if new.disqualified else new.score))
            log.info("researched %5.1f -> %5.1f %s", ev.score, new.score, facts.url)
        return summary
