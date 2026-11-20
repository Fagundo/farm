"""RentCast listings API: licensed, MLS-sourced for-sale listings (needs RENTCAST_API_KEY).

This is the automated way to cover what's on Zillow and Redfin: the same MLS listings,
through an API whose terms allow it. One request returns up to 500 listings, so a
run costs a few requests (one or two per state).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Sequence

from farmscout.domain.models import PropertyFacts, RawListing
from farmscout.sources.base import ListingSource
from farmscout.sources.redfin_csv import SQFT_PER_ACRE

ENDPOINT = "https://api.rentcast.io/v1/listings/sale"
PAGE_SIZE = 500

JsonGetter = Callable[[str, dict[str, str]], list[dict]]


def _http_get_json(url: str, headers: dict[str, str]) -> list[dict]:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def listing_url(item: dict) -> str:
    """RentCast gives no public listing page, so link to a web search for the address."""
    q = f"{item.get('formattedAddress', item.get('id', ''))} for sale"
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(q)


def item_to_listing(item: dict, source: str) -> RawListing:
    lot = item.get("lotSize")
    acres = round(lot / SQFT_PER_ACRE, 2) if lot else None
    ptype = item.get("propertyType") or "Property"
    agent = item.get("listingAgent") or {}
    office = item.get("listingOffice") or {}
    hoa_fee = (item.get("hoa") or {}).get("fee")
    contact = ", ".join(x for x in (agent.get("name"), agent.get("phone"), office.get("name")) if x)
    summary = (
        f"{ptype}"
        + (f", {item['bedrooms']} bd" if item.get("bedrooms") else "")
        + (f", {item['squareFootage']:,} sq ft" if item.get("squareFootage") else "")
        + (f", built {item['yearBuilt']}" if item.get("yearBuilt") else "")
        + (f"; {item['daysOnMarket']} days on market" if item.get("daysOnMarket") is not None else "")
        + (f"; MLS {item.get('mlsName', '')} #{item['mlsNumber']}" if item.get("mlsNumber") else "")
        + (f"; listing agent: {contact}" if contact else "")
        + "."
    )
    facts = PropertyFacts(
        url=listing_url(item),
        title=item.get("formattedAddress") or item.get("id", ""),
        source=source,
        price_usd=int(item["price"]) if item.get("price") else None,
        acres=acres,
        state=item.get("state"),
        county=item.get("county"),
        city=item.get("city"),
        latitude=item.get("latitude"),
        longitude=item.get("longitude"),
        dwellings=0 if ptype == "Land" else 1,
        property_type="land" if ptype == "Land" else "improved",
        has_hoa=(hoa_fee > 0) if isinstance(hoa_fee, (int, float)) else None,
        summary=summary,
    )
    return RawListing(url=facts.url, title=facts.title, snippet=summary, source=source, prefilled=facts)


class RentCastSource(ListingSource):
    name = "rentcast"

    def __init__(
        self,
        api_key: str,
        areas: Sequence[dict | str],
        max_price_usd: int,
        min_acres: float,
        max_acres: float,
        max_pages_per_state: int = 2,
        get_json: JsonGetter = _http_get_json,
        on_error=None,
    ) -> None:
        self._key = api_key
        # An area is a state ("WA" or {"state": "WA"}) or a circle {"lat":, "lon":, "radius": miles}.
        self._areas = [{"state": a} if isinstance(a, str) else dict(a) for a in areas]
        self._max_price = max_price_usd
        self._lot = f"{int(min_acres * SQFT_PER_ACRE)}:{int(max_acres * SQFT_PER_ACRE)}"
        self._max_pages = max_pages_per_state
        self._get = get_json
        self._on_error = on_error or (lambda state, exc: None)

    def discover(self) -> Iterator[RawListing]:
        headers = {"Accept": "application/json", "X-Api-Key": self._key}
        for area in self._areas:
            label = area.get("name") or area.get("state") or f"{area.get('lat')},{area.get('lon')}"
            where = ({"state": area["state"]} if "state" in area else
                     {"latitude": str(area["lat"]), "longitude": str(area["lon"]),
                      "radius": str(min(float(area.get("radius", 100)), 100))})
            for page in range(self._max_pages):
                params = {
                    **where,
                    "status": "Active",
                    "price": f"*:{self._max_price}",
                    "lotSize": self._lot,
                    "limit": str(PAGE_SIZE),
                    "offset": str(page * PAGE_SIZE),
                }
                try:
                    items = self._get(f"{ENDPOINT}?{urllib.parse.urlencode(params)}", headers)
                except Exception as exc:  # noqa: BLE001
                    self._on_error(label, exc)
                    break
                for item in items:
                    yield item_to_listing(item, f"{self.name}:{label}")
                if len(items) < PAGE_SIZE:
                    break
