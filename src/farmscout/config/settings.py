"""Typed settings loaded from ``criteria.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from farmscout.geo.drive_time import CountyTable, DriveTimeModel, Place


def _resolve(path: str, source_path: Path | None) -> Path:
    """Paths in the config are relative to the repo root (the config file's parent folder)."""
    p = Path(path)
    if p.is_absolute() or source_path is None or p.exists():
        return p
    return source_path.resolve().parent.parent / p


@dataclass(frozen=True)
class HardFilters:
    max_price_usd: int
    min_acres: float
    max_acres: float
    allowed_states: tuple[str, ...]
    keep_unknowns: bool = True
    max_drive_minutes_to_home: int | None = None


@dataclass(frozen=True)
class ZoningClass:
    name: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class SearchPlace:
    name: str
    state: str | None = None
    county: str | None = None


@dataclass(frozen=True)
class SearchSettings:
    max_queries: int
    results_per_query: int
    property_types: tuple[str, ...]
    places: tuple[SearchPlace, ...]
    listing_domains: tuple[str, ...]
    portal_domains: tuple[str, ...] = ()
    max_portal_queries: int | None = None
    portal_property_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class RentCastSettings:
    # Each area: a state code, {"state": ...}, or {"name", "lat", "lon", "radius"} (miles, max 100).
    areas: tuple = ("WA", "OR")
    max_pages_per_state: int = 2


@dataclass(frozen=True)
class LLMSettings:
    model: str
    max_tokens: int
    web_search_max_uses: int


@dataclass(frozen=True)
class FetchSettings:
    user_agent: str
    respect_robots: bool
    delay_seconds: float
    timeout_seconds: float
    max_chars: int


@dataclass(frozen=True)
class Settings:
    hard_filters: HardFilters
    home: Place
    metros: tuple[Place, ...]
    counties: CountyTable
    drive_model: DriveTimeModel
    zoning_classes: tuple[ZoningClass, ...]
    acreage_ideal: tuple[float, float]
    weights: dict[str, float]
    penalties: dict[str, float]
    shortlist_threshold: float
    search: SearchSettings
    llm: LLMSettings
    fetch: FetchSettings
    rentcast: RentCastSettings = RentCastSettings()
    redfin_csv_dir: Path = Path("data/inbox")
    source_path: Path | None = field(default=None, compare=False)

    @property
    def counties_by_state(self) -> dict[str, tuple[str, ...]]:
        return self.counties.by_state()

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        path = Path(path)
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        return cls.from_mapping(raw, source_path=path)

    @classmethod
    def from_mapping(cls, raw: dict, source_path: Path | None = None) -> "Settings":
        hf = raw["hard_filters"]
        s, l, f = raw["search"], raw["llm"], raw["fetch"]
        return cls(
            hard_filters=HardFilters(
                max_price_usd=int(hf["max_price_usd"]),
                min_acres=float(hf["min_acres"]),
                max_acres=float(hf["max_acres"]),
                allowed_states=tuple(hf["allowed_states"]),
                keep_unknowns=bool(hf.get("keep_unknowns", True)),
                max_drive_minutes_to_home=hf.get("max_drive_minutes_to_home"),
            ),
            home=Place(**raw["home"]),
            metros=tuple(Place(**m) for m in raw.get("metros", [])) or (Place(**raw["home"]),),
            counties=CountyTable.load(_resolve(raw["geo"]["counties_file"], source_path)),
            drive_model=DriveTimeModel(float(raw["geo"].get("road_factor", 1.2)), float(raw["geo"].get("mph", 60))),
            acreage_ideal=(
                float(raw.get("acreage", {}).get("ideal_min", hf["min_acres"])),
                float(raw.get("acreage", {}).get("ideal_max", hf["max_acres"])),
            ),
            zoning_classes=tuple(
                ZoningClass(c["name"], tuple(c["patterns"])) for c in raw["zoning"]["classes"]
            ),
            weights={k: float(v) for k, v in raw["weights"].items()},
            penalties={k: float(v) for k, v in raw.get("penalties", {}).items()},
            shortlist_threshold=float(raw.get("scoring", {}).get("shortlist_threshold", 55)),
            search=SearchSettings(
                max_queries=int(s["max_queries"]),
                results_per_query=int(s["results_per_query"]),
                property_types=tuple(s["property_types"]),
                places=tuple(SearchPlace(p) if isinstance(p, str) else SearchPlace(**p) for p in s["places"]),
                listing_domains=tuple(s.get("listing_domains", ())),
                portal_domains=tuple(s.get("portal_domains", ())),
                max_portal_queries=s.get("max_portal_queries"),
                portal_property_types=tuple(s.get("portal_property_types", ())),
            ),
            llm=LLMSettings(l["model"], int(l["max_tokens"]), int(l["web_search_max_uses"])),
            fetch=FetchSettings(
                f["user_agent"], bool(f["respect_robots"]), float(f["delay_seconds"]),
                float(f["timeout_seconds"]), int(f["max_chars"]),
            ),
            rentcast=RentCastSettings(
                areas=tuple(raw.get("rentcast", {}).get("areas", raw.get("rentcast", {}).get("states", ("WA", "OR")))),
                max_pages_per_state=int(raw.get("rentcast", {}).get("max_pages_per_state", 2)),
            ),
            redfin_csv_dir=Path(raw.get("inbox", {}).get("redfin_csv_dir", "data/inbox")),
            source_path=source_path,
        )
