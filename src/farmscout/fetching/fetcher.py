"""Fetches listing pages as plain text. Polite by default (robots.txt + delay)."""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from abc import ABC, abstractmethod
from dataclasses import dataclass
from html.parser import HTMLParser

from farmscout.config.settings import FetchSettings


class PageFetcher(ABC):
    @abstractmethod
    def fetch_text(self, url: str) -> str | None:
        """Return visible page text, or None if unavailable/blocked."""


@dataclass(frozen=True)
class FetchResult:
    """Outcome of loading a page: why it failed matters for link checking."""

    url: str
    http_status: int | None = None   # None when no response (network error, robots)
    text: str | None = None
    final_url: str | None = None     # after redirects
    blocked: bool = False            # robots.txt or 401/403/429: can't tell if the link works
    error: str = ""


class PageProbe(ABC):
    @abstractmethod
    def probe(self, url: str) -> FetchResult: ...


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self._SKIP:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self._SKIP and self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()
        elif not self._depth and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    # Page title goes on its own first line so extractors can use it as the listing title.
    return p.title + "\n" + " ".join(p.parts)


class HttpPageFetcher(PageFetcher, PageProbe):
    def __init__(self, settings: FetchSettings, on_error=None) -> None:
        self._s = settings
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._on_error = on_error or (lambda url, exc: None)

    def fetch_text(self, url: str) -> str | None:
        return self.probe(url).text

    def probe(self, url: str) -> FetchResult:
        host = urllib.parse.urlparse(url).netloc
        if self._s.respect_robots and not self._allowed(url):
            self._on_error(url, PermissionError("disallowed by robots.txt"))
            return FetchResult(url, blocked=True, error="robots.txt")
        self._throttle(host)
        req = urllib.request.Request(url, headers={"User-Agent": self._s.user_agent})
        try:
            with urllib.request.urlopen(req, timeout=self._s.timeout_seconds) as resp:
                html = resp.read().decode(resp.headers.get_content_charset() or "utf-8", "replace")
                return FetchResult(url, resp.status, html_to_text(html)[: self._s.max_chars], resp.geturl())
        except urllib.error.HTTPError as exc:
            self._on_error(url, exc)
            return FetchResult(url, exc.code, blocked=exc.code in (401, 403, 429), error=str(exc))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            self._on_error(url, exc)
            return FetchResult(url, error=str(exc))

    def _allowed(self, url: str) -> bool:
        parts = urllib.parse.urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser(f"{base}/robots.txt")
            try:
                rp.read()
            except Exception:  # noqa: BLE001 — unreachable robots.txt: treat as no rules
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self._s.user_agent, url)

    def _throttle(self, host: str) -> None:
        wait = self._s.delay_seconds - (time.monotonic() - self._last_hit.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()
