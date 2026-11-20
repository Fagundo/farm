"""Fact extraction: turn a listing's text into :class:`PropertyFacts`."""

from __future__ import annotations

from abc import ABC, abstractmethod

from farmscout.domain.models import PropertyFacts, RawListing


class FactExtractor(ABC):
    @abstractmethod
    def extract(self, listing: RawListing, page_text: str | None) -> PropertyFacts: ...


def listing_text(listing: RawListing, page_text: str | None) -> str:
    return "\n".join(p for p in (listing.title, listing.snippet, page_text or "") if p)


class LayeredExtractor(FactExtractor):
    """Primary extractor first; any field it leaves unknown is filled by the fallback.

    If the primary raises, the fallback's result is used alone.
    """

    def __init__(self, primary: FactExtractor, fallback: FactExtractor, on_error=None) -> None:
        self._primary = primary
        self._fallback = fallback
        self._on_error = on_error or (lambda listing, exc: None)

    def extract(self, listing: RawListing, page_text: str | None) -> PropertyFacts:
        backup = self._fallback.extract(listing, page_text)
        try:
            main = self._primary.extract(listing, page_text)
        except Exception as exc:  # noqa: BLE001
            self._on_error(listing, exc)
            return backup
        return main.merged_with(backup)
