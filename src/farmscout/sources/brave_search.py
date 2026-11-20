"""Optional second discovery engine: the Brave Search API (needs BRAVE_API_KEY)."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator, Sequence

from farmscout.domain.models import RawListing
from farmscout.sources.base import ListingSource

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchSource(ListingSource):
    name = "brave"

    def __init__(
        self,
        api_key: str,
        queries: Sequence[str],
        listing_domains: Sequence[str] = (),
        per_query_limit: int = 10,
        delay_seconds: float = 1.1,
        on_error=None,
    ) -> None:
        self._key = api_key
        self._queries = list(queries)
        self._domains = tuple(d.lower() for d in listing_domains)
        self._limit = per_query_limit
        self._delay = delay_seconds
        self._on_error = on_error or (lambda q, exc: None)

    def discover(self) -> Iterator[RawListing]:
        for query in self._queries:
            try:
                results = self._search(query)
            except Exception as exc:  # noqa: BLE001
                self._on_error(query, exc)
                continue
            for r in results:
                url = r.get("url", "")
                if self._domains and not any(d in urllib.parse.urlparse(url).netloc for d in self._domains):
                    continue
                yield RawListing(url, r.get("title", ""), r.get("description", ""), f"{self.name}:{query}")
            time.sleep(self._delay)

    def _search(self, query: str) -> list[dict]:
        qs = urllib.parse.urlencode({"q": query, "count": self._limit, "country": "us"})
        req = urllib.request.Request(
            f"{ENDPOINT}?{qs}",
            headers={"Accept": "application/json", "X-Subscription-Token": self._key},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data.get("web", {}).get("results", [])
