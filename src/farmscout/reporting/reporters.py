"""Report writers. Each takes ranked evaluations and writes one artifact."""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from farmscout.domain.models import Evaluation


def rank(evaluations: Sequence[Evaluation]) -> list[Evaluation]:
    return sorted((e for e in evaluations if not e.disqualified), key=lambda e: e.score, reverse=True)


class Reporter(ABC):
    @abstractmethod
    def write(self, evaluations: Sequence[Evaluation], new_urls: set[str]) -> Path: ...


class CsvReporter(Reporter):
    COLUMNS = [
        "score", "new", "title", "price_usd", "acres", "county", "state", "zoning", "zoning_class",
        "existing_uses", "water_features", "drive_minutes_to_metro", "red_flags", "to_verify", "url",
    ]

    def __init__(self, out_dir: Path) -> None:
        self._dir = out_dir

    def write(self, evaluations: Sequence[Evaluation], new_urls: set[str]) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"candidates-{date.today().isoformat()}.csv"
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=self.COLUMNS)
            w.writeheader()
            for e in rank(evaluations):
                f = e.facts
                w.writerow({
                    "score": e.score, "new": f.url in new_urls, "title": f.title, "price_usd": f.price_usd,
                    "acres": f.acres, "county": f.county, "state": f.state, "zoning": f.zoning,
                    "zoning_class": f.zoning_class, "existing_uses": "; ".join(f.existing_uses),
                    "water_features": "; ".join(f.water_features),
                    "drive_minutes_to_metro": f.drive_minutes_to_metro,
                    "red_flags": "; ".join(e.red_flags), "to_verify": "; ".join(e.to_verify), "url": f.url,
                })
        return path


class MarkdownReporter(Reporter):
    def __init__(self, out_dir: Path, shortlist_threshold: float, top_n: int = 25) -> None:
        self._dir = out_dir
        self._threshold = shortlist_threshold
        self._top = top_n

    def write(self, evaluations: Sequence[Evaluation], new_urls: set[str]) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"candidates-{date.today().isoformat()}.md"
        ranked = rank(evaluations)
        shortlist = [e for e in ranked if e.score >= self._threshold]
        lines = [
            f"# Property candidates — {date.today():%B %d, %Y}",
            "",
            f"{len(ranked)} properties passed the hard filters; {len(shortlist)} scored "
            f"{self._threshold:g}+ (shortlist). {sum(1 for e in ranked if e.facts.url in new_urls)} are new this run.",
            "",
            "| # | Score | New | Property | Price | Acres | Location | Zoning |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for i, e in enumerate(ranked[: self._top], 1):
            f = e.facts
            price = f"${f.price_usd:,}" if f.price_usd else "?"
            loc = ", ".join(x for x in (f.county and f"{f.county} Co.", f.state) if x) or "?"
            title = (f.title or f.url)[:60].replace("|", "/")
            lines.append(
                f"| {i} | {e.score:.0f} | {'★' if f.url in new_urls else ''} | [{title}]({f.url}) | {price} | "
                f"{f.acres or '?'} | {loc} | {f.zoning or '?'} |"
            )
        for i, e in enumerate(ranked[: self._top], 1):
            f = e.facts
            lines += ["", f"## {i}. {f.title or f.url} — {e.score:.0f}/100"]
            if f.summary:
                lines += ["", f.summary]
            for label, items in (("Strengths", e.strengths), ("Red flags", e.red_flags), ("To verify", e.to_verify)):
                if items:
                    lines += ["", f"**{label}**", *[f"- {x}" for x in items]]
            lines += ["", f"[Listing]({f.url})"]
        path.write_text("\n".join(lines) + "\n")
        return path
