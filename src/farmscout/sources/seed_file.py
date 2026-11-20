"""Manual leads: one URL per line (``#`` comments allowed). Lets you add listings
you find yourself, or ones an agent emails you, so they get scored the same way."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from farmscout.domain.models import RawListing
from farmscout.sources.base import ListingSource


class SeedFileSource(ListingSource):
    name = "seeds"

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def discover(self) -> Iterator[RawListing]:
        if not self._path.exists():
            return
        for line in self._path.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("http"):
                yield RawListing(url=line, source=self.name)
