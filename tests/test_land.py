"""Vacant land: zoned for the use, priced to leave room to build, scored on build readiness."""

from farmscout.domain.models import Status
from farmscout.extraction.heuristic import HeuristicExtractor
from farmscout.rules.engine import build_engine
from tests.conftest import facts, listing


def _ev(settings, enricher, **kw):
    base = dict(property_type="land", dwellings=0, has_barn=False, price_usd=400_000, county="Skagit")
    base.update(kw)
    ev = build_engine(settings).evaluate(enricher.enrich(facts(**base)))
    return ev, {o.rule_id: o for o in ev.outcomes}


def test_building_rules_do_not_apply_to_land(settings, enricher):
    ev, by = _ev(settings, enricher, zoning="Rural Commercial")
    for rid in ("convertible_buildings", "commercial_kitchen", "extra_dwelling", "existing_approved_use"):
        assert by[rid].status is Status.NOT_APPLICABLE and by[rid].max_points == 0
    assert by["build_readiness"].status is not Status.NOT_APPLICABLE


def test_land_on_resource_zoning_is_out(settings, enricher):
    ev, by = _ev(settings, enricher, zoning="EF-80")
    assert ev.disqualified and by["land_zoning"].status is Status.FAIL


def test_land_with_unknown_zoning_is_kept_and_flagged(settings, enricher):
    ev, by = _ev(settings, enricher)
    assert not ev.disqualified and any("zoning not confirmed" in r for r in ev.to_verify)


def test_land_price_cap_leaves_room_to_build(settings, enricher):
    ev, _ = _ev(settings, enricher, zoning="RC", price_usd=800_000)
    assert ev.disqualified
    improved = build_engine(settings).evaluate(enricher.enrich(facts(price_usd=800_000, dwellings=1)))
    assert not improved.disqualified  # cap is for land only


def test_ready_commercial_land_scores_well(settings, enricher):
    ready, by = _ev(settings, enricher, zoning="Rural Commercial", has_power=True, has_well=True,
                    septic="approved", road_access="paved", water_features=["creek"], in_floodplain=False,
                    has_water_rights=True, acres=10)
    assert by["build_readiness"].status is Status.PASS
    assert ready.score >= 80


def test_heuristic_reads_vacant_land_listing():
    text = ("Vacant land, 12 acres, zoned Rural Commercial. Power at the road, perc tested, "
            "community water available. Sequim, WA, Clallam County. $425,000")
    f = HeuristicExtractor().extract(listing(), text)
    assert f.property_type == "land" and f.septic == "perc_tested"
    assert f.has_power and f.has_public_water and f.zoning == "Rural Commercial"


def test_is_land_inferred_when_no_buildings():
    assert facts(dwellings=0, has_barn=False).is_land
    assert not facts(dwellings=1).is_land
    assert not facts().is_land  # unknown: treat as improved
