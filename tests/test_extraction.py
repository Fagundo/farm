import json

import pytest

from farmscout.extraction.base import LayeredExtractor
from farmscout.extraction.heuristic import HeuristicExtractor, parse_price
from farmscout.extraction.llm_extractor import LLMExtractor
from farmscout.llm.base import LLMError, parse_json_payload
from tests.conftest import ScriptedLLM, fixture_text, listing


def test_heuristic_reads_winery_listing():
    f = HeuristicExtractor().extract(listing(), fixture_text("winery_skagit.txt"))
    assert f.price_usd == 975_000
    assert f.acres == 18.5
    assert f.state == "WA" and f.county == "Skagit"
    assert {"winery", "tasting room", "wedding venue"} <= set(f.existing_uses)
    assert f.has_commercial_kitchen and f.has_water_rights and f.has_well
    assert "creek" in f.water_features
    assert f.largest_outbuilding_sqft == 4200
    assert f.dwellings == 2
    assert f.road_access == "paved"
    assert f.has_hoa is False
    assert f.zoning == "Rural Resource-NRL"


def test_heuristic_reads_rogers_rd():
    f = HeuristicExtractor().extract(listing(), fixture_text("rogers_rd.txt"))
    assert f.price_usd == 899_000 and f.acres == 20
    assert f.state == "OR" and f.county == "Yamhill"
    assert f.zoning == "EF-80"
    assert f.road_access == "gravel"


@pytest.mark.parametrize("text, expected", [
    ("Asking $1.2 million", 1_200_000), ("$850K obo", 850_000), ("$899,000", 899_000), ("$12 fee", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_parse_json_payload_handles_fences_and_prose():
    assert parse_json_payload('Here you go:\n```json\n[{"url": "x"}]\n```') == [{"url": "x"}]
    with pytest.raises(LLMError):
        parse_json_payload("no json here")


def test_llm_extractor_maps_schema():
    reply = json.dumps({"price_usd": 700000, "county": "Lane County", "existing_uses": ["Winery"],
                        "unexpected_key": 1, "water_features": ["River"]})
    f = LLMExtractor(ScriptedLLM([reply])).extract(listing(), "page")
    assert f.price_usd == 700_000 and f.county == "Lane"
    assert f.existing_uses == ["winery"] and f.water_features == ["river"]


def test_layered_extractor_fills_gaps_and_survives_failure():
    partial = json.dumps({"price_usd": 975000, "zoning": None})
    merged = LayeredExtractor(LLMExtractor(ScriptedLLM([partial])), HeuristicExtractor()).extract(
        listing(), fixture_text("winery_skagit.txt"))
    assert merged.price_usd == 975_000 and merged.county == "Skagit"

    class Boom(LLMExtractor):
        def extract(self, *a):
            raise LLMError("down")

    fallback = LayeredExtractor(Boom(ScriptedLLM([])), HeuristicExtractor()).extract(
        listing(), fixture_text("rogers_rd.txt"))
    assert fallback.zoning == "EF-80"


def test_html_to_text_keeps_title_first_and_drops_scripts():
    from farmscout.fetching.fetcher import html_to_text
    text = html_to_text("<html><head><title>Farm for sale</title><script>x()</script></head>"
                        "<body><p>20 acres</p><style>.a{}</style></body></html>")
    assert text.splitlines()[0] == "Farm for sale"
    assert "20 acres" in text and "x()" not in text
