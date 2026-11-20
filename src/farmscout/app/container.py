"""Composition root: the only place that knows which concrete classes are used."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path

from farmscout.config.settings import Settings
from farmscout.enrichment.enrichers import DriveTimeEnricher, EnrichmentChain, ZoningClassEnricher
from farmscout.extraction.base import FactExtractor, LayeredExtractor
from farmscout.extraction.heuristic import HeuristicExtractor
from farmscout.extraction.llm_extractor import LLMExtractor
from farmscout.fetching.fetcher import HttpPageFetcher
from farmscout.llm.anthropic_client import AnthropicClient
from farmscout.llm.base import LLMClient
from farmscout.pipeline import ScoutPipeline
from farmscout.reporting.reporters import CsvReporter, MarkdownReporter
from farmscout.reporting.site import SiteReporter
from farmscout.rules.engine import build_engine
from farmscout.search.query_builder import QueryBuilder
from farmscout.sources.base import CompositeSource, ListingSource
from farmscout.sources.brave_search import BraveSearchSource
from farmscout.sources.claude_search import ClaudeWebSearchSource
from farmscout.sources.seed_file import SeedFileSource
from farmscout.storage.repository import SqliteCandidateRepository
from farmscout.zoning.classifier import ZoningClassifier

log = logging.getLogger("farmscout")


def _warn(stage: str):
    return lambda what, exc: log.warning("%s error (%s): %s", stage, getattr(what, "name", what), exc)


def build_llm(settings: Settings) -> LLMClient | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return None
    s = settings.llm
    return AnthropicClient(key, s.model, s.max_tokens, s.web_search_max_uses)


def build_sources(settings: Settings, names: Sequence[str], llm: LLMClient | None, seeds: Path) -> ListingSource:
    queries = QueryBuilder(settings.search, settings.hard_filters.max_price_usd).build()
    sources: list[ListingSource] = []
    for name in names:
        if name == "seeds":
            sources.append(SeedFileSource(seeds))
        elif name == "claude":
            if llm is None:
                log.warning("Skipping 'claude' source: ANTHROPIC_API_KEY not set")
                continue
            sources.append(ClaudeWebSearchSource(
                llm, queries, settings.search.listing_domains, settings.search.results_per_query,
                on_error=_warn("claude search")))
        elif name == "brave":
            key = os.environ.get("BRAVE_API_KEY", "")
            if not key:
                log.warning("Skipping 'brave' source: BRAVE_API_KEY not set")
                continue
            sources.append(BraveSearchSource(
                key, queries, settings.search.listing_domains, settings.search.results_per_query,
                on_error=_warn("brave search")))
        else:
            raise ValueError(f"Unknown source '{name}' (use: claude, brave, seeds)")
    return CompositeSource(sources, on_error=_warn("source"))


def build_extractor(llm: LLMClient | None) -> FactExtractor:
    heuristic = HeuristicExtractor()
    if llm is None:
        return heuristic
    return LayeredExtractor(LLMExtractor(llm), heuristic, on_error=_warn("llm extract"))


def build_pipeline(
    settings: Settings,
    *,
    sources: Sequence[str] = ("claude", "seeds"),
    db_path: Path = Path("data/farmscout.sqlite"),
    reports_dir: Path = Path("reports"),
    seeds_path: Path = Path("config/seeds.txt"),
    site_dir: Path = Path("site"),
) -> ScoutPipeline:
    llm = build_llm(settings)
    return ScoutPipeline(
        source=build_sources(settings, sources, llm, seeds_path),
        fetcher=HttpPageFetcher(settings.fetch, on_error=_warn("fetch")),
        extractor=build_extractor(llm),
        enricher=EnrichmentChain([
            ZoningClassEnricher(ZoningClassifier(settings.zoning_classes)),
            DriveTimeEnricher(settings.drive_minutes),
        ]),
        engine=build_engine(settings),
        repository=SqliteCandidateRepository(db_path),
        reporters=[
            CsvReporter(reports_dir),
            MarkdownReporter(reports_dir, settings.shortlist_threshold),
            SiteReporter(site_dir, settings.shortlist_threshold),
        ],
    )

