"""Typed settings loaded from ``criteria.toml``."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class HardFilters:
    max_price_usd: int
    min_acres: float
    max_acres: float
    allowed_states: tuple[str, ...]
    keep_unknowns: bool = True


@dataclass(frozen=True)
class ZoningClass:
    name: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class SearchSettings:
    max_queries: int
    results_per_query: int
    property_types: tuple[str, ...]
    places: tuple[str, ...]
    listing_domains: tuple[str, ...]
    portal_domains: tuple[str, ...] = ()
    max_portal_queries: int | None = None
    portal_property_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class RentCastSettings:
    states: tuple[str, ...] = ("WA", "OR")
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
    counties_by_state: dict[str, tuple[str, ...]]
    drive_minutes: dict[str, dict[str, int]]  # state -> county -> minutes
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
            ),
            counties_by_state={st: tuple(v["drive_minutes"]) for st, v in raw.get("regions", {}).items()},
            drive_minutes={
                st: {c: int(m) for c, m in v["drive_minutes"].items()}
                for st, v in raw.get("regions", {}).items()
            },
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
                places=tuple(s["places"]),
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
                states=tuple(raw.get("rentcast", {}).get("states", ("WA", "OR", "ID"))),
                max_pages_per_state=int(raw.get("rentcast", {}).get("max_pages_per_state", 2)),
            ),
            redfin_csv_dir=Path(raw.get("inbox", {}).get("redfin_csv_dir", "data/inbox")),
            source_path=source_path,
        )
