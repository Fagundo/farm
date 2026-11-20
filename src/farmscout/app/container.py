"""Composition root: the only place that knows which concrete classes are used."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from farmscout.config.settings import Settings
from farmscout.enrichment.enrichers import (
    CountyFromCoordinatesEnricher,
    DriveTimeEnricher,
    EnrichmentChain,
    ZoningClassEnricher,
)
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
from farmscout.sources.redfin_csv import RedfinCsvSource
from farmscout.sources.rentcast import RentCastSource
from farmscout.sources.seed_file import SeedFileSource
from farmscout.storage.repository import SqliteCandidateRepository, normalize_url
from farmscout.research.claude_researcher import ClaudeResearcher
from farmscout.research.file_researcher import FileResearcher
from farmscout.research.stage import ResearchPolicy, ResearchStage
from farmscout.verification.link_checker import LinkChecker
from farmscout.verification.stage import VerificationStage
from farmscout.zoning.classifier import ZoningClassifier

log = logging.getLogger("farmscout")

DEFAULT_SOURCES = ("claude", "portals", "rentcast", "redfin_csv", "seeds")


def _warn(stage: str):
    return lambda what, exc: log.warning("%s error (%s): %s", stage, getattr(what, "name", what), exc)


def build_llm(settings: Settings) -> LLMClient | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return None
    s = settings.llm
    return AnthropicClient(key, s.model, s.max_tokens, s.web_search_max_uses)


def build_query_builder(settings: Settings, seed: int | None = None) -> QueryBuilder:
    """Query builder whose place weights come from drive time to home."""
    def distance(place) -> int | None:
        county = settings.counties.get(place.state, place.county)
        if county is None:
            return None
        return settings.drive_model.minutes(county.lat, county.lon, settings.home,
                                            road_factor=county.road_factor, adjust_min=county.adjust_min)
    return QueryBuilder(settings.search, settings.hard_filters.max_price_usd, seed, distance)


@dataclass(frozen=True)
class SourceContext:
    settings: Settings
    llm: LLMClient | None
    seeds: Path

    def _builder(self) -> QueryBuilder:
        return build_query_builder(self.settings)

    @property
    def queries(self) -> list[str]:
        return self._builder().build()

    @property
    def portal_queries(self) -> list[str]:
        return self._builder().build_portal()


def _needs_llm(name: str, ctx: SourceContext) -> LLMClient | None:
    if ctx.llm is None:
        log.warning("Skipping '%s' source: ANTHROPIC_API_KEY not set", name)
    return ctx.llm


def _env(name: str, var: str) -> str:
    value = os.environ.get(var, "")
    if not value:
        log.warning("Skipping '%s' source: %s not set", name, var)
    return value


def _claude(ctx: SourceContext) -> ListingSource | None:
    llm = _needs_llm("claude", ctx)
    s = ctx.settings.search
    return llm and ClaudeWebSearchSource(llm, ctx.queries, s.listing_domains, s.results_per_query,
                                         on_error=_warn("claude search"))


def _portals(ctx: SourceContext) -> ListingSource | None:
    llm = _needs_llm("portals", ctx)
    s = ctx.settings.search
    return llm and ClaudeWebSearchSource(
        llm, ctx.portal_queries, s.portal_domains, s.results_per_query,
        on_error=_warn("portal search"), allowed_domains=s.portal_domains, name="portals")


def _brave(ctx: SourceContext) -> ListingSource | None:
    key = _env("brave", "BRAVE_API_KEY")
    s = ctx.settings.search
    return key and BraveSearchSource(key, ctx.queries, s.listing_domains, s.results_per_query,
                                     on_error=_warn("brave search"))


def _rentcast(ctx: SourceContext) -> ListingSource | None:
    key = _env("rentcast", "RENTCAST_API_KEY")
    hf, rc = ctx.settings.hard_filters, ctx.settings.rentcast
    return key and RentCastSource(key, rc.areas, hf.max_price_usd, hf.min_acres, hf.max_acres,
                                  rc.max_pages_per_state, on_error=_warn("rentcast"))


# Registry: source name -> factory. Adding a source = one factory + one entry.
SOURCE_FACTORIES: dict[str, Callable[[SourceContext], ListingSource | None]] = {
    "claude": _claude,
    "portals": _portals,
    "brave": _brave,
    "rentcast": _rentcast,
    "redfin_csv": lambda ctx: RedfinCsvSource(ctx.settings.redfin_csv_dir),
    "seeds": lambda ctx: SeedFileSource(ctx.seeds),
}


def build_sources(settings: Settings, names: Sequence[str], llm: LLMClient | None, seeds: Path) -> ListingSource:
    ctx = SourceContext(settings, llm, seeds)
    sources: list[ListingSource] = []
    for name in names:
        factory = SOURCE_FACTORIES.get(name.strip())
        if factory is None:
            raise ValueError(f"Unknown source '{name}' (use: {', '.join(SOURCE_FACTORIES)})")
        if source := factory(ctx):
            sources.append(source)
    return CompositeSource(sources, on_error=_warn("source"))


def build_extractor(llm: LLMClient | None) -> FactExtractor:
    heuristic = HeuristicExtractor()
    if llm is None:
        return heuristic
    return LayeredExtractor(LLMExtractor(llm), heuristic, on_error=_warn("llm extract"))


def build_enricher(settings: Settings) -> EnrichmentChain:
    return EnrichmentChain([
        ZoningClassEnricher(ZoningClassifier(settings.zoning_classes)),
        CountyFromCoordinatesEnricher(settings.counties),
        DriveTimeEnricher(settings.counties, settings.home, settings.metros, settings.drive_model),
    ])


def build_research_stage(
    settings: Settings,
    *,
    db_path: Path,
    from_file: Path | None = None,
    policy: ResearchPolicy = ResearchPolicy(),
    mode: str = "full",
) -> ResearchStage | None:
    """Claude-backed research, or replay of saved findings when ``from_file`` is given."""
    selector = None
    if from_file is not None:
        researcher = FileResearcher(from_file)
        wanted = {normalize_url(u) for u in researcher.urls}
        selector = lambda ev: normalize_url(ev.facts.url) in wanted  # noqa: E731
        policy = replace(policy, top_n=len(wanted))
    else:
        llm = build_llm(settings)
        if llm is None:
            log.warning("Skipping research: ANTHROPIC_API_KEY not set")
            return None
        researcher = ClaudeResearcher(llm, mode)
    return ResearchStage(researcher, build_enricher(settings), build_engine(settings),
                         SqliteCandidateRepository(db_path), policy, selector)


def build_verification_stage(settings: Settings, *, db_path: Path) -> VerificationStage:
    fetcher = HttpPageFetcher(settings.fetch, on_error=lambda url, exc: None)
    return VerificationStage(LinkChecker(fetcher), build_enricher(settings), build_engine(settings),
                             SqliteCandidateRepository(db_path))


def build_pipeline(
    settings: Settings,
    *,
    sources: Sequence[str] = DEFAULT_SOURCES,
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
        enricher=build_enricher(settings),
        engine=build_engine(settings),
        repository=SqliteCandidateRepository(db_path),
        reporters=[
            CsvReporter(reports_dir),
            MarkdownReporter(reports_dir, settings.shortlist_threshold),
            SiteReporter(site_dir, settings.shortlist_threshold),
        ],
    )

