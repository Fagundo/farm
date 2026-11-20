"""Regex/keyword extractor. Free, offline, and good enough as a fallback."""

from __future__ import annotations

import re

from farmscout.domain.models import PropertyFacts, RawListing
from farmscout.extraction.base import FactExtractor, listing_text

_PRICE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(million|mil|m\b|k\b)?", re.I)
_ACRES = re.compile(r"(\d{1,4}(?:\.\d+)?)\s*(?:\+/-\s*|±\s*)?(?:acres?|ac\b)", re.I)
_ZONING = re.compile(r"[Zz]on(?:ed|ing)\s*(?:is|:|-)?\s*([A-Z][A-Za-z0-9\-/ ]{1,40}?)(?=[.,;)\n]|\s(?:with|and|which|that|allows?|per)\b|\s{2}|$)", re.M)
_COUNTY = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+County\b")
_US_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
    "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY"
).split()
_STATE = re.compile(r",\s*(" + "|".join(_US_STATES) + r")\b|\b(Washington|Oregon)\b")
_SQFT_BLDG = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d{3,5})\s*(?:sq\.?\s?ft\.?|sf|square feet)\s+(?:\w+\s){0,2}(barn|shop|building|outbuilding|arena|warehouse)",
    re.I,
)

_USES = {
    "winery": r"\bwinery\b", "tasting room": r"tasting room", "event venue": r"event (?:venue|center|space)",
    "wedding venue": r"wedding", "restaurant": r"\brestaurant\b|\bcafe\b", "retreat center": r"retreat",
    "bed and breakfast": r"bed (?:and|&) breakfast|\bB&B\b", "lodge": r"\blodge\b", "inn": r"\binn\b",
    "cidery": r"cidery", "brewery": r"brewery", "distillery": r"distillery", "farm stand": r"farm stand",
    "campground": r"campground|\bRV park\b", "guest ranch": r"guest ranch",
}
_WATER = {
    "creek": r"\bcreek\b", "river": r"\briver(?:front| frontage)?\b", "pond": r"\bpond\b",
    "lake": r"\blake(?:front)?\b", "shoreline": r"waterfront|shoreline|beach|sound frontage|bay frontage",
    "spring": r"\bsprings?\b(?! water heater)",
}
_STATE_ABBR = {"washington": "WA", "oregon": "OR"}


def _any(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


def parse_price(text: str) -> int | None:
    best = None
    for num, unit in _PRICE.findall(text):
        value = float(num.replace(",", ""))
        unit = unit.lower()
        if unit in {"million", "mil", "m"}:
            value *= 1_000_000
        elif unit == "k":
            value *= 1_000
        if 50_000 <= value <= 20_000_000:
            best = int(value) if best is None else best  # first plausible = asking price
    return best


class HeuristicExtractor(FactExtractor):
    def extract(self, listing: RawListing, page_text: str | None) -> PropertyFacts:
        text = listing_text(listing, page_text)
        acres = [float(a) for a in _ACRES.findall(text) if 0.1 <= float(a) <= 5000]
        zoning = _ZONING.search(text)
        county = _COUNTY.search(text)
        state = None
        if m := _STATE.search(text):
            state = m.group(1) or _STATE_ABBR[m.group(2).lower()]
        sqfts = [int(n.replace(",", "")) for n, _ in _SQFT_BLDG.findall(text)]

        no_hoa = _any(r"no\s+hoa|hoa:\s*no|hoa\s+fees?:\s*(?:none|\$?0\b|-)", text)
        has_hoa = False if no_hoa else (True if _any(r"\bHOA\b|homeowners'? association", text) else None)

        road = None
        if _any(r"shared (?:private )?(?:road|drive(?:way)?)|road maintenance agreement|private road", text):
            road = "shared_private"
        elif _any(r"paved (?:road|access|frontage)|blacktop|highway frontage", text):
            road = "paved"
        elif _any(r"gravel|rock road", text):
            road = "gravel"

        dwellings = None
        if _any(r"\bADU\b|guest (?:house|cottage)|second (?:home|residence|dwelling)|two homes|2 homes|mother[- ]in[- ]law|caretaker", text):
            dwellings = 2
        elif _any(r"\b\d\s*(?:bed|br|bedroom)", text):
            dwellings = 1

        land = _any(r"vacant land|raw land|bare land|undeveloped (?:land|acreage)|\bland only\b|lots?/land|buildable (?:lot|acreage)", text)
        septic = None
        if _any(r"septic (?:design |permit )?approved|approved septic|septic (?:system )?design", text):
            septic = "approved"
        elif _any(r"perc(?:olation)? test(?:ed)?|perc'?d|passed perc", text):
            septic = "perc_tested"
        elif _any(r"septic (?:tank|system) (?:on site|installed|in place)|existing septic|\bseptic\b", text) and not land:
            septic = "existing"
        power = True if _any(r"power (?:at|to|on|available)|electric(?:ity)? (?:at|to|on|available)|power to (?:the )?(?:site|property|road)|utilities (?:at|to) (?:the )?(?:road|site)", text) else None
        public_water = True if _any(r"(?:public|community|city|pud) water", text) else None

        return PropertyFacts(
            url=listing.url,
            title=listing.title or _first_line(page_text),
            source=listing.source,
            price_usd=parse_price(text),
            acres=acres[0] if acres else None,
            state=state,
            county=county.group(1) if county else None,
            zoning=zoning.group(1).strip() if zoning else None,
            existing_uses=sorted(u for u, p in _USES.items() if _any(p, text)),
            has_water_rights=True if _any(r"water rights?", text) else None,
            has_well=True if _any(r"\bwell\b(?! maintained| kept| cared)", text) else None,
            water_features=sorted(w for w, p in _WATER.items() if _any(p, text)),
            has_commercial_kitchen=True if _any(r"commercial(?:-grade)? kitchen|commissary", text) else None,
            dwellings=dwellings,
            has_barn=True if _any(r"\bbarn\b|\bshop\b|pole building|outbuilding", text) else None,
            largest_outbuilding_sqft=max(sqfts) if sqfts else None,
            road_access=road,
            property_type="land" if land else None,
            has_power=power,
            has_public_water=public_water,
            septic=septic,
            in_floodplain=True if _any(r"flood ?plain|flood zone", text) else None,
            has_hoa=has_hoa,
        )
