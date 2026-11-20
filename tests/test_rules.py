from farmscout.domain.models import Status
from farmscout.rules.engine import build_engine
from tests.conftest import facts


def _by_id(ev):
    return {o.rule_id: o for o in ev.outcomes}


def test_price_over_cap_disqualifies(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(price_usd=1_200_000)))
    assert ev.disqualified
    assert _by_id(ev)["price_cap"].status is Status.FAIL


def test_unknown_price_kept_but_flagged(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(price_usd=None)))
    assert not ev.disqualified
    assert any("Price not found" in r for r in ev.to_verify)


def test_out_of_region_county_disqualifies(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(state="WA", county="Gotham")))
    assert ev.disqualified


def test_other_state_disqualifies(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(state="CA", county="Sonoma")))
    assert ev.disqualified


def test_commercial_zoning_beats_farm_only(settings, enricher):
    engine = build_engine(settings)
    commercial = engine.evaluate(enricher.enrich(facts(zoning="Rural Commercial")))
    farm = engine.evaluate(enricher.enrich(facts(zoning="EF-80")))
    assert commercial.score > farm.score
    assert any("Resource zoning" in r for r in farm.red_flags)


def test_existing_winery_overrides_farm_zoning_penalty(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(zoning="EFU", existing_uses=["winery"])))
    by = _by_id(ev)
    assert by["commercial_pathway"].status is Status.PASS
    assert by["farm_only_no_existing_use"].points == 0


def test_ideal_property_scores_high(settings, enricher):
    ideal = facts(
        zoning="Rural Commercial", existing_uses=["event venue"], has_water_rights=True,
        water_features=["creek"], in_floodplain=False, largest_outbuilding_sqft=3000,
        has_commercial_kitchen=True, dwellings=2, road_access="paved", county="King",
    )
    ev = build_engine(settings).evaluate(enricher.enrich(ideal))
    assert ev.score >= 95
    assert not ev.red_flags


def test_penalties_reduce_score(settings, enricher):
    engine = build_engine(settings)
    clean = engine.evaluate(enricher.enrich(facts(zoning="RR-5")))
    flagged = engine.evaluate(enricher.enrich(facts(zoning="RR-5", has_hoa=True, in_floodplain=True)))
    assert flagged.score < clean.score


def test_unknown_weight_in_config_is_rejected(settings):
    import dataclasses
    import pytest
    bad = dataclasses.replace(settings, weights={**settings.weights, "hot_tub": 5})
    with pytest.raises(ValueError, match="hot_tub"):
        build_engine(bad)


def test_acreage_fit_partial_outside_ideal(settings, enricher):
    engine = build_engine(settings)
    by = lambda a: _by_id(engine.evaluate(enricher.enrich(facts(acres=a))))["acreage_fit"]
    assert by(20).status is Status.PASS
    assert by(3).status is Status.PARTIAL and by(120).status is Status.PARTIAL
    assert not engine.evaluate(enricher.enrich(facts(acres=150))).disqualified
    assert engine.evaluate(enricher.enrich(facts(acres=200))).disqualified


def test_drive_time_is_keyed_by_state(enricher):
    assert enricher.enrich(facts(state="WA", county="Lincoln")).drive_minutes_to_metro == 50
    assert enricher.enrich(facts(state="OR", county="Lincoln")).drive_minutes_to_metro == 140


def test_idaho_in_range(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(state="ID", county="Bonner")))
    assert not ev.disqualified
