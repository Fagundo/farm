"""LLM extractor: asks Claude to read the listing and fill a fixed JSON schema."""

from __future__ import annotations

from farmscout.domain.models import PropertyFacts, RawListing
from farmscout.extraction.base import FactExtractor, listing_text
from farmscout.llm.base import LLMClient, parse_json_payload

SYSTEM = """You extract facts from a real-estate listing. Use ONLY what the text states; \
use null when a fact is not stated. Do not guess zoning from the location.

Return ONLY a JSON object with exactly these keys:
{
  "price_usd": int|null,              // asking price
  "acres": float|null,
  "state": "WA"|"OR"|other 2-letter|null,
  "county": str|null,                 // county name without the word County
  "city": str|null,
  "zoning": str|null,                 // the zoning designation as written, e.g. "EF-80", "RR-5", "Rural Commercial"
  "existing_uses": [str],             // from: winery, tasting room, event venue, wedding venue, restaurant,
                                      // retreat center, bed and breakfast, lodge, inn, cidery, brewery,
                                      // distillery, farm stand, campground, guest ranch — only if operating or permitted
  "has_water_rights": bool|null,
  "has_well": bool|null,
  "water_features": [str],            // from: creek, river, pond, lake, shoreline, spring
  "has_commercial_kitchen": bool|null,
  "dwellings": int|null,              // number of homes/ADUs/cabins that are dwellings
  "has_barn": bool|null,              // barn, shop or large outbuilding
  "largest_outbuilding_sqft": int|null,
  "road_access": "paved"|"gravel"|"shared_private"|null,
  "in_floodplain": bool|null,
  "has_hoa": bool|null,
  "summary": str                      // one sentence on fit for farm + sauna + events
}"""

_ALLOWED = {
    "price_usd", "acres", "state", "county", "city", "zoning", "existing_uses", "has_water_rights",
    "has_well", "water_features", "has_commercial_kitchen", "dwellings", "has_barn",
    "largest_outbuilding_sqft", "road_access", "in_floodplain", "has_hoa", "summary",
}


class LLMExtractor(FactExtractor):
    def __init__(self, llm: LLMClient, max_chars: int = 15000) -> None:
        self._llm = llm
        self._max_chars = max_chars

    def extract(self, listing: RawListing, page_text: str | None) -> PropertyFacts:
        text = listing_text(listing, page_text)[: self._max_chars]
        data = parse_json_payload(self._llm.complete(SYSTEM, f"URL: {listing.url}\n\n{text}"))
        if not isinstance(data, dict):
            raise ValueError("Extractor expected a JSON object")
        clean = {k: v for k, v in data.items() if k in _ALLOWED}
        if isinstance(clean.get("county"), str):
            clean["county"] = clean["county"].removesuffix(" County").strip()
        for list_key in ("existing_uses", "water_features"):
            clean[list_key] = [str(x).lower() for x in clean.get(list_key) or []]
        return PropertyFacts(url=listing.url, title=listing.title, source=listing.source, **clean)
