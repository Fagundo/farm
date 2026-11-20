from __future__ import annotations

from pathlib import Path

import pytest

from farmscout.config.settings import Settings
from farmscout.domain.models import PropertyFacts, RawListing
from farmscout.enrichment.enrichers import (
    CountyFromCoordinatesEnricher,
    DriveTimeEnricher,
    EnrichmentChain,
    ZoningClassEnricher,
)
from farmscout.fetching.fetcher import PageFetcher
from farmscout.llm.base import LLMClient
from farmscout.zoning.classifier import ZoningClassifier

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.load(ROOT / "config" / "criteria.toml")


@pytest.fixture
def enricher(settings):
    from farmscout.app.container import build_enricher
    return build_enricher(settings)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text()


class FixtureFetcher(PageFetcher):
    """Serves page text from tests/fixtures keyed by URL."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def fetch_text(self, url: str) -> str | None:
        return self.pages.get(url)


class ScriptedLLM(LLMClient):
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str, bool]] = []

    def complete(self, system: str, user: str, *, web_search: bool = False, allowed_domains=()) -> str:
        self.calls.append((system, user, web_search))
        self.domains = list(allowed_domains)
        return self.replies.pop(0)


def facts(**kw) -> PropertyFacts:
    base = dict(url="https://example.com/p", state="WA", county="Skagit", price_usd=850_000, acres=20.0)
    base.update(kw)
    return PropertyFacts(**base)


def listing(url: str = "https://example.com/p", **kw) -> RawListing:
    return RawListing(url=url, **kw)
