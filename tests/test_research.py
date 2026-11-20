import json

from farmscout.research.base import ResearchResult
from farmscout.research.claude_researcher import ClaudeResearcher
from farmscout.research.file_researcher import FileResearcher
from farmscout.research.stage import ResearchPolicy, ResearchStage
from farmscout.rules.engine import build_engine
from farmscout.storage.repository import SqliteCandidateRepository
from tests.conftest import ScriptedLLM, facts


def test_apply_fills_gaps_but_keeps_listing_facts():
    f = facts(zoning="RR-5", price_usd=900_000, water_features=["creek"])
    out = ResearchResult(f.url, {"zoning": "AB", "price_usd": 850_000, "has_well": True, "url": "x",
                                 "water_features": ["pond"], "listing_status": "active"},
                         "ok", ["https://src"]).apply_to(f)
    assert out.zoning == "RR-5"            # stated by listing: kept
    assert out.price_usd == 850_000        # prices go stale: research wins
    assert out.has_well is True and out.url == f.url
    assert out.water_features == ["creek", "pond"]
    assert out.listing_status == "active" and out.research_sources == ["https://src"] and out.researched_at


def test_claude_researcher_parses_reply():
    reply = json.dumps({"updates": {"listing_status": "sold", "county": "Linn County", "existing_uses": ["Winery"]},
                        "notes": "Sold in March.", "sources": ["https://a", "not-a-url"]})
    llm = ScriptedLLM([reply])
    r = ClaudeResearcher(llm).research(facts(), ["Zoning not found"])
    assert r.updates["county"] == "Linn" and r.updates["existing_uses"] == ["winery"]
    assert r.sources == ["https://a"] and llm.calls[0][2] is True and "Zoning not found" in llm.calls[0][1]


def _repo_with(tmp_path, settings, enricher, *items):
    repo = SqliteCandidateRepository(tmp_path / "db")
    engine = build_engine(settings)
    for f in items:
        repo.save(engine.evaluate(enricher.enrich(f)))
    return repo, engine


def test_stage_researches_top_candidates_and_rules_out_sold(tmp_path, settings, enricher):
    good = facts(url="https://ex.com/good", zoning="Rural Commercial")
    meh = facts(url="https://ex.com/meh")
    repo, engine = _repo_with(tmp_path, settings, enricher, good, meh)

    class Sold:
        def research(self, f, q):
            return ResearchResult(f.url, {"listing_status": "sold"}, "Sold.", [])

    s = ResearchStage(Sold(), enricher, engine, repo, ResearchPolicy(top_n=1)).run()
    assert s.researched == 1 and s.score_changes[0][0] == "https://ex.com/good"
    by_url = {c.evaluation.facts.url: c.evaluation for c in repo.all()}
    assert by_url["https://ex.com/good"].disqualified and not by_url["https://ex.com/meh"].disqualified

    # Freshly researched candidates are not due again.
    again = ResearchStage(Sold(), enricher, engine, repo, ResearchPolicy(top_n=5, include_disqualified=True)).run()
    assert again.considered == 1  # only "meh"


def test_file_researcher_matches_normalized_urls(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps([{"url": "https://www.ex.com/a/?utm_source=x", "updates": {"listing_status": "pending"}}]))
    fr = FileResearcher(path)
    assert fr.research(facts(url="http://ex.com/a"), []).updates["listing_status"] == "pending"
    assert fr.research(facts(url="https://ex.com/b"), []) is None


def test_site_uses_canonical_link(tmp_path, settings, enricher):
    from farmscout.reporting.site import site_payload
    ev = build_engine(settings).evaluate(enricher.enrich(facts(canonical_url="https://good.example/listing")))
    assert site_payload([ev], set(), 55)["candidates"][0]["canonical_url"] == "https://good.example/listing"
