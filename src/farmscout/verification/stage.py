"""Link-check stage: verify every candidate's link, record status the page states, re-score."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from farmscout.enrichment.enrichers import Enricher
from farmscout.rules.engine import RuleEngine
from farmscout.storage.repository import CandidateRepository
from farmscout.verification.link_checker import LinkChecker

log = logging.getLogger("farmscout")


@dataclass
class VerifySummary:
    checked: int = 0
    by_status: Counter = field(default_factory=Counter)
    newly_sold: list[str] = field(default_factory=list)


class VerificationStage:
    def __init__(self, checker: LinkChecker, enricher: Enricher, engine: RuleEngine,
                 repository: CandidateRepository, include_disqualified: bool = False) -> None:
        self._checker = checker
        self._enricher = enricher
        self._engine = engine
        self._repo = repository
        self._include_dq = include_disqualified

    def run(self) -> VerifySummary:
        summary = VerifySummary()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for stored in self._repo.all():
            ev = stored.evaluation
            if ev.disqualified and not self._include_dq:
                continue
            check = self._checker.check(ev.facts)
            summary.checked += 1
            summary.by_status[check.link_status] += 1
            changes = {"link_status": check.link_status, "link_checked_at": now}
            # A page that plainly says sold/pending is better evidence than our stored status.
            if check.page_listing_status in {"sold", "pending"}:
                changes["listing_status"] = check.page_listing_status
                if check.page_listing_status == "sold" and ev.facts.listing_status != "sold":
                    summary.newly_sold.append(ev.facts.url)
            facts = self._enricher.enrich(replace(ev.facts, **changes))
            self._repo.save(self._engine.evaluate(facts))
            log.info("link %-14s %s %s", check.link_status, check.page_listing_status or "", check.url)
        return summary
