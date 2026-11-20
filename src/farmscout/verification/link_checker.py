"""Checks that a listing link loads, shows THIS property, and whether it says sold/pending."""

from __future__ import annotations

import re
from dataclasses import dataclass

from farmscout.domain.models import PropertyFacts
from farmscout.fetching.fetcher import FetchResult, PageProbe

# Only the top of the page is the listing itself; lower down are "similar homes sold nearby".
HEAD_CHARS = 4000

_STATUS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("sold", re.compile(
        r"\b(?:listing\s+)?status\s*[:\-]?\s*(?:sold|closed)\b"
        r"|\bthis (?:home|property|listing) (?:has )?(?:sold|been sold|is sold)\b"
        r"|\bsold (?:on|for)\s+(?:\$|\d|\w+ \d)"
        r"|\b(?:off[- ]market|no longer (?:available|for sale|on the market))\b", re.I)),
    ("pending", re.compile(
        r"\b(?:listing\s+)?status\s*[:\-]?\s*(?:pending|contingent|under contract|sale pending)\b"
        r"|\bpending (?:inspection|sale)\b", re.I)),
    ("active", re.compile(r"\b(?:listing\s+)?status\s*[:\-]?\s*(?:active|for sale)\b", re.I)),
]
_ADDRESS = re.compile(r"\b(\d{2,6})\s+((?:[NSEW]\.?\s+)?[A-Za-z0-9]{2,})")
_PAGE_GONE = re.compile(r"\b(?:page not found|404|listing (?:not found|removed|has been removed))\b", re.I)


@dataclass(frozen=True)
class LinkCheck:
    url: str
    link_status: str            # ok | broken | wrong_property | blocked | unreachable
    page_listing_status: str | None = None  # sold | pending | active, as the page states it
    detail: str = ""


def address_tokens(facts: PropertyFacts) -> tuple[str, str] | None:
    """Street number and the first word of the street name, if the title has an address."""
    m = _ADDRESS.search(facts.title or "")
    if not m:
        return None
    word = m.group(2).split()[-1].rstrip(".")
    return m.group(1), word


def detect_status(text: str) -> str | None:
    head = text[:HEAD_CHARS]
    for status, pattern in _STATUS_PATTERNS:
        if pattern.search(head):
            return status
    return None


class LinkChecker:
    def __init__(self, probe: PageProbe) -> None:
        self._probe = probe

    def check(self, facts: PropertyFacts) -> LinkCheck:
        url = facts.link
        result: FetchResult = self._probe.probe(url)
        if result.blocked:
            return LinkCheck(url, "blocked", detail=result.error or f"HTTP {result.http_status}")
        if result.http_status is None:
            return LinkCheck(url, "unreachable", detail=result.error)
        if result.http_status >= 400 or not result.text:
            return LinkCheck(url, "broken", detail=f"HTTP {result.http_status}")
        text = result.text
        tokens = address_tokens(facts)
        if tokens:
            number, word = tokens
            if not (re.search(rf"\b{number}\b", text) and re.search(rf"\b{re.escape(word)}", text, re.I)):
                if _PAGE_GONE.search(text[:HEAD_CHARS]):
                    return LinkCheck(url, "broken", detail="page says the listing is gone")
                return LinkCheck(url, "wrong_property",
                                 detail=f"page doesn't mention {number} {word} (redirected to a search page?)")
        return LinkCheck(url, "ok", detect_status(text))
