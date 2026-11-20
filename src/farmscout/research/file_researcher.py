"""Researcher that replays findings saved in a JSON file (manual research, or a past run).

File format: a list of {"url": ..., "updates": {...}, "notes": "...", "sources": [...],
"force": [field names to overwrite even if the listing stated them]}.
"""

from __future__ import annotations

import json
from pathlib import Path

from farmscout.domain.models import PropertyFacts
from farmscout.research.base import PropertyResearcher, ResearchResult
from farmscout.storage.repository import normalize_url


class FileResearcher(PropertyResearcher):
    def __init__(self, path: str | Path) -> None:
        items = json.loads(Path(path).read_text())
        self._by_url = {
            normalize_url(i["url"]): ResearchResult(i["url"], i.get("updates", {}), i.get("notes", ""),
                                                     i.get("sources", []), i.get("force", []))
            for i in items
        }

    @property
    def urls(self) -> set[str]:
        return {r.url for r in self._by_url.values()}

    def research(self, facts: PropertyFacts, open_questions: list[str]) -> ResearchResult | None:
        return self._by_url.get(normalize_url(facts.url))
