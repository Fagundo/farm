"""Listing sources discover candidate URLs. Each is independent and swappable."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator

from farmscout.domain.models import RawListing


class ListingSource(ABC):
    name: str = "source"

    @abstractmethod
    def discover(self) -> Iterable[RawListing]: ...


class CompositeSource(ListingSource):
    """Fans out to several sources; one failing source does not stop the others."""

    name = "composite"

    def __init__(self, sources: Iterable[ListingSource], on_error=None) -> None:
        self._sources = list(sources)
        self._on_error = on_error or (lambda src, exc: None)

    def discover(self) -> Iterator[RawListing]:
        for src in self._sources:
            try:
                yield from src.discover()
            except Exception as exc:  # noqa: BLE001 — isolate source failures
                self._on_error(src, exc)
