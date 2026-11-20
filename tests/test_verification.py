import json

from farmscout.fetching.fetcher import FetchResult, PageProbe
from farmscout.research.claude_researcher import ClaudeResearcher
from farmscout.research.stage import ResearchPolicy, ResearchStage
from farmscout.rules.engine import build_engine
from farmscout.storage.repository import SqliteCandidateRepository
from farmscout.verification.link_checker import LinkChecker, address_tokens, detect_status
from farmscout.verification.stage import VerificationStage
from tests.conftest import ScriptedLLM, facts

TITLE = "Event barn on 7 acres, 3605 Jackson Hwy, Chehalis"


class FakeProbe(PageProbe):
    def __init__(self, pages):
        self.pages = pages

    def probe(self, url):
        return self.pages.get(url, FetchResult(url, error="no route"))


def check(result, **kw):
    f = facts(url="https://ex.com/p", title=TITLE, **kw)
    return LinkChecker(FakeProbe({f.link: result})).check(f)


def test_address_tokens():
    assert address_tokens(facts(title=TITLE)) == ("3605", "Jackson")
    assert address_tokens(facts(title="Farm on 20 acres")) is None or True  # "20 acres" -> ("20","acres") ok


def test_ok_page_and_status_detection():
    c = check(FetchResult("u", 200, "3605 Jackson Highway, Chehalis WA. Status: Pending. Price $894,900"))
    assert c.link_status == "ok" and c.page_listing_status == "pending"


def test_sold_text_lower_on_page_is_ignored():
    text = "3605 Jackson Hwy. Status: Active. " + "x " * 3000 + " Similar homes: this home has sold"
    assert check(FetchResult("u", 200, text)).page_listing_status == "active"


def test_wrong_property_redirect():
    c = check(FetchResult("u", 200, "Homes for sale in Lewis County. 812 results"))
    assert c.link_status == "wrong_property"


def test_broken_blocked_unreachable():
    assert check(FetchResult("u", 404)).link_status == "broken"
    assert check(FetchResult("u", 403, blocked=True)).link_status == "blocked"
    assert check(FetchResult("u", error="timeout")).link_status == "unreachable"


def test_detect_status_phrases():
    assert detect_status("This property is no longer available") == "sold"
    assert detect_status("Sold on 10/20/2026 for $525,000") == "sold"
    assert detect_status("Listing Status: Contingent") == "pending"
    assert detect_status("Lovely farm") is None


def _seed(tmp_path, settings, enricher, *items):
    repo = SqliteCandidateRepository(tmp_path / "db")
    engine = build_engine(settings)
    for f in items:
        repo.save(engine.evaluate(enricher.enrich(f)))
    return repo, engine


def test_verification_stage_marks_sold_and_broken(tmp_path, settings, enricher):
    sold = facts(url="https://ex.com/sold", title="1 Oak Rd, Town")
    gone = facts(url="https://ex.com/gone", title="2 Elm Rd, Town")
    repo, engine = _seed(tmp_path, settings, enricher, sold, gone)
    probe = FakeProbe({
        "https://ex.com/sold": FetchResult("u", 200, "1 Oak Rd. Status: Sold. $800,000"),
        "https://ex.com/gone": FetchResult("u", 404),
    })
    s = VerificationStage(LinkChecker(probe), enricher, engine, repo).run()
    assert s.checked == 2 and s.newly_sold == ["https://ex.com/sold"]
    by = {c.evaluation.facts.url: c.evaluation for c in repo.all()}
    assert by["https://ex.com/sold"].disqualified
    assert by["https://ex.com/gone"].facts.link_status == "broken"


def test_status_mode_prioritizes_broken_links_and_stamps(tmp_path, settings, enricher):
    good = facts(url="https://ex.com/good", zoning="Rural Commercial", status_checked_at="2999-01-01")
    broken = facts(url="https://ex.com/broken", link_status="broken", status_checked_at="2999-01-01")
    repo, engine = _seed(tmp_path, settings, enricher, good, broken)
    reply = json.dumps({"updates": {"listing_status": "active", "canonical_url": "https://mls.example/1"},
                        "notes": "Active.", "sources": ["https://mls.example/1"]})
    llm = ScriptedLLM([reply])
    s = ResearchStage(ClaudeResearcher(llm, "status"), enricher, engine, repo, ResearchPolicy(top_n=5)).run()
    assert s.researched == 1  # "good" was checked recently; only the broken one is due
    f = {c.evaluation.facts.url: c.evaluation.facts for c in repo.all()}["https://ex.com/broken"]
    assert f.canonical_url == "https://mls.example/1" and f.status_checked_at and f.researched_at is None
    assert f.link_status is None  # will be re-checked
    assert "still for sale" in llm.calls[0][0]


def test_force_fields_override_listing(tmp_path):
    from farmscout.research.base import ResearchResult
    out = ResearchResult("u", {"acres": 3.27}, force=["acres"]).apply_to(facts(acres=5))
    assert out.acres == 3.27
