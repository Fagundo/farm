"""Maps free-text zoning designations to coarse classes the rules reason about."""

from __future__ import annotations

import re
from collections.abc import Sequence

from farmscout.config.settings import ZoningClass


class ZoningClassifier:
    """First-match-wins regex classifier. Order of ``classes`` is priority order."""

    def __init__(self, classes: Sequence[ZoningClass]) -> None:
        self._compiled = [
            (c.name, [re.compile(p, re.IGNORECASE) for p in c.patterns]) for c in classes
        ]

    def classify(self, zoning: str | None) -> str | None:
        if not zoning:
            return None
        for name, patterns in self._compiled:
            if any(p.search(zoning) for p in patterns):
                return name
        return "other"
