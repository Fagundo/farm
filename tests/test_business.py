from farmscout.business import BusinessFitAssessor, BusinessUseCatalog, Fit, SettingDetector
from farmscout.business.uses import DEFAULT_BUSINESS_USES
from farmscout.domain.models import RawListing, Status
from farmscout.extraction.heuristic import HeuristicExtractor
from farmscout.rules.engine import build_engine
from tests.conftest import facts


def _by_id(ev):
    return {o.rule_id: o for o in ev.outcomes}


def test_config_loads_three_business_types(settings):
    assert [u.key for u in settings.business_uses] == ["venue", "food", "wellness"]


def test_existing_spa_counts_as_wellness_and_existing_use(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(zoning="RR-5", existing_uses=["spa"])))
    by = _by_id(ev)
    assert ev.facts.business_fits["wellness"] == "existing"
    assert ev.facts.business_fits["venue"] == "conditional"
    assert by["business_pathway"].status is Status.PASS
    assert "Spa / sauna" in by["business_pathway"].reason
    assert by["existing_approved_use"].status is Status.PASS


def test_existing_cafe_on_resource_land_is_grandfathered(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(zoning="EFU", existing_uses=["cafe"])))
    by = _by_id(ev)
    assert ev.facts.business_fits["food"] == "existing"
    assert by["farm_only_no_existing_use"].points == 0


def test_resort_zone_fits_spa_and_venue():
    a = BusinessFitAssessor(BusinessUseCatalog(DEFAULT_BUSINESS_USES))
    fits = a.fits(facts(zoning="Rural Resort", zoning_class=None))
    assert fits["wellness"] == Fit.LIKELY.value and fits["venue"] == Fit.LIKELY.value


def test_resource_land_only_gets_limited_venue_credit(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(zoning="EF-80")))
    assert ev.facts.business_fits == {"venue": "limited", "food": "unlikely", "wellness": "unlikely"}
    assert _by_id(ev)["business_pathway"].status is Status.PARTIAL


def test_weight_favors_preferred_business():
    from dataclasses import replace
    uses = [replace(u, weight=2.0 if u.key == "wellness" else 1.0) for u in DEFAULT_BUSINESS_USES]
    a = BusinessFitAssessor(BusinessUseCatalog(uses))
    best, credit = a.best(facts(zoning="RR-5", zoning_class="mixed", existing_uses=["restaurant"]))
    assert best.use.key == "food" and credit == 0.5  # existing food, half weight


def test_setting_detector():
    d = SettingDetector()
    assert d.detect("Secluded 20 acres at the end of the road") == "secluded"
    assert d.detect("34 acres with I-5 frontage") == "roadside"
    assert d.detect("6.66 acres zoned Rural Commercial on Hwy 101, Sequim") == "roadside"
    assert d.detect("Peaceful farm with Hwy 20 frontage") == "roadside"
    assert d.detect("Commercial land near Hwy 18") is None


def test_secluded_outscores_roadside(settings, enricher):
    engine = build_engine(settings)
    quiet = engine.evaluate(enricher.enrich(facts(zoning="RR-5", summary="Private, secluded setting")))
    road = engine.evaluate(enricher.enrich(facts(zoning="RR-5", title="Acreage with highway frontage")))
    assert quiet.score > road.score
    assert _by_id(road)["seclusion"].status is Status.FAIL


def test_under_five_acres_is_ruled_out(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(acres=3.45)))
    assert ev.disqualified


def test_heuristic_finds_spa_and_setting():
    text = "Day spa and bathhouse on 12 secluded acres bordering national forest. Zoned RR-5. Washington."
    f = HeuristicExtractor().extract(RawListing(url="https://x/1"), text)
    assert {"spa", "bathhouse"} <= set(f.existing_uses)
    assert f.setting == "secluded"


def test_vacant_land_excluded_when_switched_off(settings, enricher):
    assert settings.include_land is False
    ev = build_engine(settings).evaluate(enricher.enrich(facts(property_type="land", zoning="Rural Commercial")))
    assert ev.disqualified
    assert _by_id(ev)["vacant_land"].status is Status.FAIL
    farm = build_engine(settings).evaluate(enricher.enrich(facts(has_barn=True, dwellings=1)))
    assert _by_id(farm)["vacant_land"].status is Status.NOT_APPLICABLE
