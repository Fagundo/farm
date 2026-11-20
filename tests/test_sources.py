"""Structured sources: Redfin CSV export, RentCast API, and portal-restricted search."""

import json

from farmscout.pipeline import ScoutPipeline
from farmscout.extraction.heuristic import HeuristicExtractor
from farmscout.rules.engine import build_engine
from farmscout.sources.claude_search import ClaudeWebSearchSource
from farmscout.sources.redfin_csv import RedfinCsvSource
from farmscout.sources.rentcast import RentCastSource, item_to_listing
from farmscout.storage.repository import SqliteCandidateRepository
from tests.conftest import FIXTURES, FixtureFetcher, ScriptedLLM


def test_redfin_csv_parses_active_rows_only(tmp_path):
    (tmp_path / "export.csv").write_text((FIXTURES / "redfin_export.csv").read_text())
    found = list(RedfinCsvSource(tmp_path).discover())
    assert [l.prefilled.title for l in found] == ["123 Farm Rd, Sedro-Woolley", "0 River Rd, Concrete"]
    farm = found[0].prefilled
    assert farm.price_usd == 785_000 and farm.acres == 15.0 and farm.state == "WA"
    assert farm.dwellings == 1 and found[1].prefilled.dwellings == 0
    assert farm.url.startswith("https://www.redfin.com/")


def test_redfin_csv_missing_inbox_yields_nothing(tmp_path):
    assert list(RedfinCsvSource(tmp_path / "nope").discover()) == []


SAMPLE = {
    "id": "1-Creek-Ln,-Sequim,-WA-98382", "formattedAddress": "1 Creek Ln, Sequim, WA 98382",
    "city": "Sequim", "state": "WA", "county": "Clallam", "propertyType": "Single Family",
    "bedrooms": 3, "squareFootage": 2100, "lotSize": 871200, "price": 925000, "status": "Active",
    "daysOnMarket": 12, "mlsName": "NWMLS", "mlsNumber": "999",
    "listingAgent": {"name": "Pat Agent", "phone": "3605550100"}, "hoa": {"fee": 0},
}


def test_rentcast_item_mapping():
    l = item_to_listing(SAMPLE, "rentcast:WA")
    f = l.prefilled
    assert (f.price_usd, f.acres, f.county, f.has_hoa, f.dwellings) == (925_000, 20.0, "Clallam", False, 1)
    assert "Pat Agent" in f.summary and l.url.startswith("https://www.google.com/search?q=1+Creek+Ln")


def test_rentcast_builds_filtered_queries_and_paginates():
    calls = []

    def fake_get(url, headers):
        calls.append(url)
        assert headers["X-Api-Key"] == "k"
        return [SAMPLE] * (500 if len(calls) == 1 else 3)

    src = RentCastSource("k", ["WA"], 1_000_000, 5, 80, max_pages_per_state=3, get_json=fake_get)
    assert len(list(src.discover())) == 503
    assert len(calls) == 2  # stopped after a short page
    assert "lotSize=217800%3A3484800" in calls[0] and "price=%2A%3A1000000" in calls[0]
    assert "offset=500" in calls[1]


def test_rentcast_error_is_isolated():
    errors = []

    def boom(url, headers):
        raise OSError("down")

    src = RentCastSource("k", ["WA", "OR"], 1, 5, 80, get_json=boom, on_error=lambda s, e: errors.append(s))
    assert list(src.discover()) == [] and errors == ["WA", "OR"]


def test_portal_search_restricts_domains():
    llm = ScriptedLLM([json.dumps([{"url": "https://www.zillow.com/homedetails/x", "title": "x"}])])
    src = ClaudeWebSearchSource(llm, ["q"], allowed_domains=["zillow.com", "redfin.com"], name="portals")
    assert [l.url for l in src.discover()] == ["https://www.zillow.com/homedetails/x"]
    assert llm.domains == ["zillow.com", "redfin.com"] and src.name == "portals"


def test_prefilled_facts_win_and_skip_extraction_when_page_blocked(tmp_path, settings, enricher):
    class Source:
        def discover(self):
            yield item_to_listing(SAMPLE, "rentcast:WA")

    p = ScoutPipeline(Source(), FixtureFetcher({}), HeuristicExtractor(), enricher, build_engine(settings),
                      SqliteCandidateRepository(tmp_path / "db"), [])
    s = p.run()
    ev = p._repo.all()[0].evaluation
    assert s.evaluated == 1 and not ev.disqualified
    assert ev.facts.county == "Clallam" and ev.facts.drive_minutes_to_metro == 150
