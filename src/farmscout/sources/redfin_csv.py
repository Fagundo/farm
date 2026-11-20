"""Redfin's own export: the "Download All" CSV at the bottom of a search's list view.

Redfin offers this download on most searches (up to 350 homes, and only when a search
has 20+ results). Save a search on redfin.com with your filters (WA/OR, 5–80 acres,
under $1M), download the CSV, and drop it in ``data/inbox/``. Every run reads the inbox;
homes already in the database are skipped, so leaving old files there is harmless.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from farmscout.domain.models import PropertyFacts, RawListing
from farmscout.sources.base import ListingSource

SQFT_PER_ACRE = 43_560


def _num(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _column(row: dict[str, str], *prefixes: str) -> str | None:
    """Look up a column by case-insensitive prefix (Redfin's URL header is very long)."""
    for key, value in row.items():
        if key and any(key.strip().upper().startswith(p) for p in prefixes):
            return value
    return None


def row_to_listing(row: dict[str, str], source: str) -> RawListing | None:
    url = (_column(row, "URL") or "").strip()
    price = _num(_column(row, "PRICE"))
    if not url.startswith("http") or price is None:
        return None  # disclaimer rows and rows without a listing link
    status = (_column(row, "STATUS") or "").strip()
    if status and status.lower() not in {"active", "coming soon", "for sale"}:
        return None
    lot_sqft = _num(_column(row, "LOT SIZE"))
    beds = _num(_column(row, "BEDS"))
    hoa = _num(_column(row, "HOA"))
    ptype = (_column(row, "PROPERTY TYPE") or "").strip()
    address = (_column(row, "ADDRESS") or "").strip()
    city = (_column(row, "CITY") or "").strip()
    state = (_column(row, "STATE") or "").strip().upper() or None
    acres = round(lot_sqft / SQFT_PER_ACRE, 2) if lot_sqft else None

    facts = PropertyFacts(
        url=url,
        title=", ".join(x for x in (address, city) if x) or url,
        source=source,
        price_usd=int(price),
        acres=acres,
        state=state,
        city=city or None,
        dwellings=(1 if beds else 0) if ptype.lower() != "vacant land" else 0,
        has_hoa=(hoa > 0) if hoa is not None else None,
        summary=f"Redfin export: {ptype or 'property'}"
        + (f", {int(beds)} bd" if beds else "")
        + (f", {acres:g} acres" if acres else "")
        + (f", {_column(row, 'DAYS ON MARKET')} days on market" if _column(row, "DAYS ON MARKET") else "")
        + ".",
    )
    snippet = f"{facts.title}, {state or ''} {_column(row, 'ZIP') or ''}. ${int(price):,}. {facts.summary}"
    return RawListing(url=url, title=facts.title, snippet=snippet, source=source, prefilled=facts)


class RedfinCsvSource(ListingSource):
    name = "redfin_csv"

    def __init__(self, inbox: str | Path) -> None:
        self._inbox = Path(inbox)

    def discover(self) -> Iterator[RawListing]:
        if not self._inbox.exists():
            return
        for path in sorted(self._inbox.glob("*.csv")):
            with path.open(newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    listing = row_to_listing(row, f"{self.name}:{path.name}")
                    if listing:
                        yield listing
