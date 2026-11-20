"""Research: look a property up beyond its listing page and fill in what the listing left out."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone
from typing import Any

from farmscout.domain.models import PropertyFacts

# Research may replace these even when the listing stated them: they go stale.
OVERRIDABLE = {"listing_status", "price_usd", "canonical_url"}
# Never touched by research.
PROTECTED = {"url", "source", "title", "zoning_class", "drive_minutes_to_metro"}


@dataclass
class ResearchResult:
    """What a researcher found about one property."""

    url: str
    updates: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    sources: list[str] = field(default_factory=list)

    def apply_to(self, facts: PropertyFacts) -> PropertyFacts:
        known = {f.name for f in fields(PropertyFacts)} - PROTECTED
        changes: dict[str, Any] = {}
        for key, value in self.updates.items():
            if key not in known or value is None or value == "" or value == []:
                continue
            current = getattr(facts, key)
            if key in OVERRIDABLE or current is None or current == "" or current == []:
                changes[key] = value
            elif isinstance(current, list) and isinstance(value, list):
                changes[key] = sorted(set(current) | set(value))
        notes = "\n".join(x for x in (facts.research_notes, self.notes) if x).strip()
        return replace(
            facts,
            **changes,
            research_notes=notes,
            research_sources=sorted(set(facts.research_sources) | set(self.sources)),
            researched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )


class PropertyResearcher(ABC):
    @abstractmethod
    def research(self, facts: PropertyFacts, open_questions: list[str]) -> ResearchResult | None:
        """Return findings for ``facts`` (None if nothing was found)."""
