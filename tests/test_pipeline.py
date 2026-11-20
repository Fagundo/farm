"""End-to-end with fakes: no network, real rules/extraction/storage/reports."""

import json

from farmscout.domain.models import RawListing
from farmscout.extraction.heuristic import HeuristicExtractor
from farmscout.pipeline import ScoutPipeline
from farmscout.reporting.reporters import CsvReporter, MarkdownReporter
from farmscout.rules.engine import build_engine
from farmscout.sources.base import CompositeSource, ListingSource
from farmscout.sources.claude_search import ClaudeWebSearchSource
from farmscout.storage.repository import SqliteCandidateRepository, normalize_url
from tests.conftest import FixtureFetcher, ScriptedLLM, fixture_text

PAGES = {
    "https://ex.com/winery": "winery_skagit.txt",
    "https://ex.com/rogers": "rogers_rd.txt",
    "https://ex.com/lodge": "rural_commercial_kitsap.txt",
    "https://ex.com/pricey": "too_expensive.txt",
    "https://ex.com/ca": "california.txt",
}


class ListSource(ListingSource):
    name = "list"

    def __init__(self, urls):
        self.urls = urls

    def discover(self):
        for u in self.urls:
            yield RawListing(url=u, source=self.name)


def _pipeline(tmp_path, settings, enricher, source):
    return ScoutPipeline(
        source=source,
        fetcher=FixtureFetcher({u: fixture_text(f) for u, f in PAGES.items()}),
        extractor=HeuristicExtractor(),
        enricher=enricher,
        engine=build_engine(settings),
        repository=SqliteCandidateRepository(tmp_path / "db.sqlite"),
        reporters=[CsvReporter(tmp_path), MarkdownReporter(tmp_path, settings.shortlist_threshold)],
    )


def test_end_to_end_ranks_and_filters(tmp_path, settings, enricher):
    urls = list(PAGES) + ["https://ex.com/winery?utm_source=x"]  # duplicate via tracking param
    p = _pipeline(tmp_path, settings, enricher, ListSource(urls))
    s = p.run()
    assert s.discovered == 5 and s.evaluated == 5 and s.disqualified == 2 and s.new == 5

    ranked = sorted((c.evaluation for c in p._repo.all() if not c.evaluation.disqualified),
                    key=lambda e: e.score, reverse=True)
    order = [e.facts.url for e in ranked]
    assert order[-1] == "https://ex.com/rogers"  # EF-80 farm with no venue use ranks last
    assert set(order[:2]) == {"https://ex.com/winery", "https://ex.com/lodge"}

    md = next(r for r in s.reports if r.suffix == ".md").read_text()
    assert "Skagit Valley Winery" in md and "Sonoma" not in md

    # Second run skips everything already seen.
    s2 = p.run()
    assert s2.skipped_seen == 5 and s2.evaluated == 0


def test_claude_source_parses_results_and_skips_bad_items():
    reply = json.dumps([{"url": "https://ex.com/a", "title": "A", "snippet": "$900,000"},
                        {"url": "not-a-url"}, "junk"])
    llm = ScriptedLLM([reply, "sorry, nothing"])
    errors = []
    src = ClaudeWebSearchSource(llm, ["q1", "q2"], on_error=lambda q, e: errors.append(q))
    found = list(src.discover())
    assert [f.url for f in found] == ["https://ex.com/a"]
    assert llm.calls[0][2] is True  # web search enabled
    assert errors == ["q2"]


def test_composite_source_isolates_failures():
    class Broken(ListingSource):
        def discover(self):
            raise RuntimeError("boom")
            yield

    errs = []
    out = list(CompositeSource([Broken(), ListSource(["https://ex.com/x"])],
                               on_error=lambda s, e: errs.append(e)).discover())
    assert [o.url for o in out] == ["https://ex.com/x"] and len(errs) == 1


def test_normalize_url():
    assert normalize_url("http://www.Ex.com/a/?utm_source=z&b=1") == "https://ex.com/a?b=1"


def test_import_facts_scores_without_fetching(tmp_path, settings, enricher):
    from farmscout.domain.models import PropertyFacts
    p = _pipeline(tmp_path, settings, enricher, ListSource([]))
    s = p.import_facts([PropertyFacts(url="https://ex.com/z", state="OR", county="Linn",
                                      price_usd=500_000, acres=10, zoning="AB (Agri-Business)")])
    ev = p._repo.all()[0].evaluation
    assert s.evaluated == 1 and ev.facts.zoning_class == "mixed" and ev.facts.nearest_metro == "Portland"


def test_site_reporter_embeds_escaped_data(tmp_path, settings, enricher):
    import json
    from farmscout.domain.models import PropertyFacts
    from farmscout.reporting.site import SiteReporter
    ev = build_engine(settings).evaluate(enricher.enrich(PropertyFacts(
        url="https://ex.com/s", title="Barn </script><b>x", state="WA", county="King", price_usd=800_000, acres=10)))
    path = SiteReporter(tmp_path / "site", settings.shortlist_threshold).write([ev], {"https://ex.com/s"})
    html = path.read_text()
    assert "__FARMSCOUT_DATA__" not in html and "</script><b>" not in html
    data = json.loads((tmp_path / "site" / "data.json").read_text())
    assert data["candidates"][0]["new"] is True and data["candidates"][0]["title"].startswith("Barn")
