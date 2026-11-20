"""Researcher backed by Claude with web search: county GIS, MLS mirrors, news, planning records."""

from __future__ import annotations

import json

from farmscout.domain.models import PropertyFacts
from farmscout.llm.base import LLMClient, parse_json_payload
from farmscout.research.base import PropertyResearcher, ResearchResult

SYSTEM = """You research one rural property for a buyer who wants to run a small farm plus a \
sauna and an event space or farm-to-table dinners. Use web search: other listing sites for \
the same address (brokerages, MLS mirrors), county assessor/GIS and zoning maps, FEMA flood \
information, state water-rights records, county permit or planning records, and news.

Answer the open questions first. Then:
- listing_status: is it still for sale? Use "active", "pending", "sold" or "off_market"; \
  report a newer price if it changed.
- canonical_url: if the given URL is stale, a search page or for a different property, give a \
  working page that shows THIS listing (prefer brokerage or MLS mirror pages).
- Fill any other fields you can confirm.

Rules: only report what a source states. Never guess. Every fact must be backed by a URL in \
"sources". Use null for anything not found.

Respond with ONLY this JSON object:
{
  "updates": {
    "listing_status": "active"|"pending"|"sold"|"off_market"|null,
    "price_usd": int|null, "canonical_url": str|null,
    "acres": float|null, "county": str|null, "state": str|null, "city": str|null,
    "zoning": str|null, "existing_uses": [str], "has_water_rights": bool|null, "has_well": bool|null,
    "water_features": [str], "has_commercial_kitchen": bool|null, "dwellings": int|null,
    "has_barn": bool|null, "largest_outbuilding_sqft": int|null,
    "road_access": "paved"|"gravel"|"shared_private"|null, "in_floodplain": bool|null, "has_hoa": bool|null
  },
  "notes": str,          // 1-3 sentences: what you confirmed and anything a buyer should know
  "sources": [str]       // URLs you relied on
}"""

FIELDS = (
    "url", "title", "price_usd", "acres", "state", "county", "city", "zoning", "existing_uses",
    "has_water_rights", "has_well", "water_features", "has_commercial_kitchen", "dwellings",
    "has_barn", "largest_outbuilding_sqft", "road_access", "in_floodplain", "has_hoa", "summary",
    "listing_status",
)


class ClaudeResearcher(PropertyResearcher):
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def research(self, facts: PropertyFacts, open_questions: list[str]) -> ResearchResult | None:
        known = {k: getattr(facts, k) for k in FIELDS}
        user = (
            "Property as currently recorded:\n"
            + json.dumps(known, indent=1)
            + "\n\nOpen questions:\n"
            + "\n".join(f"- {q}" for q in open_questions or ["Confirm status and fill gaps"])
        )
        data = parse_json_payload(self._llm.complete(SYSTEM, user, web_search=True))
        if not isinstance(data, dict):
            return None
        updates = data.get("updates") or {}
        for key in ("existing_uses", "water_features"):
            if isinstance(updates.get(key), list):
                updates[key] = [str(x).lower() for x in updates[key]]
        if isinstance(updates.get("county"), str):
            updates["county"] = updates["county"].removesuffix(" County").strip()
        sources = [s for s in data.get("sources") or [] if isinstance(s, str) and s.startswith("http")]
        return ResearchResult(facts.url, updates, str(data.get("notes") or ""), sources)
