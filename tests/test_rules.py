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
    wa = enricher.enrich(facts(state="WA", county="Lincoln"))
    ore = enricher.enrich(facts(state="OR", county="Lincoln"))
    assert wa.nearest_metro == "Spokane" and ore.nearest_metro == "Portland"
    assert wa.drive_minutes_to_home < ore.drive_minutes_to_home


def test_drive_time_calibration(enricher):
    hours = lambda st, c: enricher.enrich(facts(state=st, county=c)).drive_minutes_to_home / 60
    assert hours("WA", "King") < 1 and 1 < hours("WA", "Skagit") < 1.5
    assert 2.5 < hours("WA", "San Juan") < 4      # ferry penalty
    assert 4 < hours("WA", "Spokane") < 5
    assert 6.5 < hours("MT", "Missoula") < 8.5


def test_property_coordinates_beat_county(enricher):
    f = enricher.enrich(facts(state="WA", county="King", latitude=47.61, longitude=-122.33))
    assert f.drive_minutes_to_home <= 5


def test_home_proximity_favors_seattle(settings, enricher):
    engine = build_engine(settings)
    near = engine.evaluate(enricher.enrich(facts(state="WA", county="Skagit")))
    far = engine.evaluate(enricher.enrich(facts(state="MT", county="Flathead")))
    assert near.score > far.score
    assert _by_id(near)["home_proximity"].status is Status.PASS
    assert _by_id(far)["home_proximity"].status is Status.PARTIAL


def test_too_far_from_home_is_out(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(state="MT", county="Gallatin", price_usd=500_000)))
    assert not ev.disqualified or any("from Seattle" in r for r in ev.red_flags)
    far = facts(state="CA", county="Shasta", latitude=36.0, longitude=-119.0)
    assert build_engine(settings).evaluate(enricher.enrich(far)).disqualified


def test_idaho_in_range(settings, enricher):
    ev = build_engine(settings).evaluate(enricher.enrich(facts(state="ID", county="Bonner")))
    assert not ev.disqualified


def test_query_sampling_favors_places_near_home(settings):
    from farmscout.app.container import build_query_builder
    near = far = 0
    for seed in range(20):
        for q in build_query_builder(settings, seed=seed).build():
            near += " WA " in q
            far += " MT " in q or " CA " in q
    assert near > 5 * far > 0
