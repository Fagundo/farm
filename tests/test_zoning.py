import pytest

from farmscout.zoning.classifier import ZoningClassifier


@pytest.mark.parametrize(
    "zoning, expected",
    [
        ("EF-80", "farm_only"),
        ("Exclusive Farm Use", "farm_only"),
        ("APD", "farm_only"),
        ("Commercial Agriculture", "farm_only"),
        ("Rural Commercial", "commercial"),
        ("RC", "commercial"),
        ("Tourist Commercial", "commercial"),
        ("AF-10", "mixed"),
        ("RR-5", "mixed"),
        ("Rural Residential", "mixed"),
        ("F-80", "forest_only"),
        ("Something Odd", "other"),
        (None, None),
    ],
)
def test_classify(settings, zoning, expected):
    assert ZoningClassifier(settings.zoning_classes).classify(zoning) == expected


def test_skagit_resource_lands_are_farm_only(settings):
    assert ZoningClassifier(settings.zoning_classes).classify("Rural Resource-NRL") == "farm_only"
