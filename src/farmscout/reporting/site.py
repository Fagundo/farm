"""Static, self-contained web page for sharing results (GitHub Pages or any host)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

from farmscout.domain.models import Evaluation
from farmscout.reporting.reporters import Reporter

PLACEHOLDER = "__FARMSCOUT_DATA__"


def site_payload(evaluations: Sequence[Evaluation], new_urls: set[str], threshold: float) -> dict:
    candidates = []
    for e in sorted(evaluations, key=lambda e: e.score, reverse=True):
        row = e.facts.to_dict()
        row.update(
            score=e.score,
            disqualified=e.disqualified,
            new=e.facts.url in new_urls,
            strengths=e.strengths,
            red_flags=e.red_flags,
            to_verify=e.to_verify,
        )
        candidates.append(row)
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "threshold": threshold,
        "candidates": candidates,
    }


class SiteReporter(Reporter):
    """Writes ``<out_dir>/index.html`` with the data embedded, plus ``data.json``."""

    def __init__(self, out_dir: Path, shortlist_threshold: float) -> None:
        self._dir = out_dir
        self._threshold = shortlist_threshold

    def write(self, evaluations: Sequence[Evaluation], new_urls: set[str]) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = site_payload(evaluations, new_urls, self._threshold)
        (self._dir / "data.json").write_text(json.dumps(payload, indent=1))
        # Escape "</" so listing text can never close the <script> tag early.
        embedded = json.dumps(payload).replace("</", "<\\/")
        template = files("farmscout.reporting").joinpath("templates/site.html").read_text()
        path = self._dir / "index.html"
        path.write_text(template.replace(PLACEHOLDER, embedded))
        return path
