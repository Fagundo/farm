"""Approximate drive times from coordinates (no routing service needed).

minutes = great-circle miles x road_factor / mph x 60 + adjust_min

Calibrated on Seattle->Portland (~175 min), ->Spokane (~270), ->Bend (~330). Ferries and slow
coastal roads are handled per county in ``config/counties.csv``.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

EARTH_RADIUS_MILES = 3958.8


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class County:
    state: str
    name: str
    lat: float
    lon: float
    road_factor: float | None = None
    adjust_min: int = 0


def great_circle_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


class DriveTimeModel:
    def __init__(self, road_factor: float = 1.2, mph: float = 60.0) -> None:
        self._factor = road_factor
        self._mph = mph

    def minutes(self, lat: float, lon: float, to: Place, *, road_factor: float | None = None,
                adjust_min: int = 0) -> int:
        miles = great_circle_miles(lat, lon, to.lat, to.lon) * (road_factor or self._factor)
        return int(round(miles / self._mph * 60 + adjust_min))


class CountyTable:
    """Counties in the search area, keyed by (STATE, county lowercased)."""

    def __init__(self, counties: list[County]) -> None:
        self._by_key = {(c.state.upper(), c.name.lower()): c for c in counties}

    @classmethod
    def load(cls, path: str | Path) -> "CountyTable":
        rows = [l for l in Path(path).read_text().splitlines() if l.strip() and not l.startswith("#")]
        counties = []
        for r in csv.DictReader(rows):
            counties.append(County(
                state=r["state"].strip(), name=r["county"].strip(), lat=float(r["lat"]), lon=float(r["lon"]),
                road_factor=float(r["road_factor"]) if r.get("road_factor") else None,
                adjust_min=int(r["adjust_min"]) if r.get("adjust_min") else 0,
            ))
        return cls(counties)

    def get(self, state: str | None, county: str | None) -> County | None:
        if not state or not county:
            return None
        return self._by_key.get((state.upper(), county.lower().removesuffix(" county").strip()))

    def nearest(self, state: str, lat: float, lon: float) -> County | None:
        candidates = [c for (st, _), c in self._by_key.items() if st == state.upper()]
        if not candidates:
            return None
        return min(candidates, key=lambda c: great_circle_miles(lat, lon, c.lat, c.lon))

    def by_state(self) -> dict[str, tuple[str, ...]]:
        out: dict[str, list[str]] = {}
        for c in self._by_key.values():
            out.setdefault(c.state.upper(), []).append(c.name)
        return {k: tuple(sorted(v)) for k, v in out.items()}
