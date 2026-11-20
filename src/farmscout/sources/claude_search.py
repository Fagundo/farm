"""Discovers listings by letting Claude run web searches and return listing URLs."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from farmscout.domain.models import RawListing
from farmscout.llm.base import LLMClient, LLMError, parse_json_payload
from farmscout.sources.base import ListingSource

SYSTEM = """You are a real-estate research assistant. Use web search to find SPECIFIC \
properties currently listed for sale that match the query. Only include individual \
listing pages (not search-result pages, articles, or agent home pages). Prefer these \
domains when possible: {domains}.

Respond with ONLY a JSON array (no prose). Each item:
{{"url": str, "title": str, "snippet": str}}
The snippet should include any price, acreage, location, zoning and features you saw. \
Return [] if nothing qualifies. Never invent URLs."""


class ClaudeWebSearchSource(ListingSource):
    name = "claude_web_search"

    def __init__(
        self,
        llm: LLMClient,
        queries: Sequence[str],
        listing_domains: Sequence[str] = (),
        per_query_limit: int = 10,
        on_error=None,
        allowed_domains: Sequence[str] = (),
        name: str | None = None,
    ) -> None:
        self._llm = llm
        self._allowed = tuple(allowed_domains)
        if name:
            self.name = name
        self._queries = list(queries)
        self._system = SYSTEM.format(domains=", ".join(listing_domains) or "any")
        self._limit = per_query_limit
        self._on_error = on_error or (lambda q, exc: None)

    def discover(self) -> Iterator[RawListing]:
        for query in self._queries:
            try:
                reply = self._llm.complete(self._system, f"Query: {query}", web_search=True,
                                           allowed_domains=self._allowed)
                items = parse_json_payload(reply)
            except LLMError as exc:
                self._on_error(query, exc)
                continue
            if not isinstance(items, list):
                continue
            for item in items[: self._limit]:
                url = (item or {}).get("url") if isinstance(item, dict) else None
                if url and url.startswith("http"):
                    yield RawListing(
                        url=url,
                        title=str(item.get("title", "")),
                        snippet=str(item.get("snippet", "")),
                        source=f"{self.name}:{query}",
                    )
