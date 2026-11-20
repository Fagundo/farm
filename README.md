# farmscout

Finds and ranks Pacific Northwest properties for a **farm + sauna + event space / farm-to-table** business.
It searches the web, reads each listing, scores it against the rules in `config/criteria.toml`,
remembers what it has already seen, and writes a ranked Markdown + CSV report.

Standard library only (Python 3.11+). Claude does the web searching and the listing reading.

## Quick start

```bash
pip install -e ".[dev]"            # or just run with PYTHONPATH=src
export ANTHROPIC_API_KEY=sk-ant-...
export BRAVE_API_KEY=...            # optional second search engine

farmscout queries                   # see the searches the config generates
farmscout run --limit 25            # discover + score up to 25 new properties
farmscout run --sources claude,brave,seeds
farmscout evaluate https://...      # score one listing and print every rule's verdict
farmscout report                    # rebuild reports and site/index.html from the database
farmscout import data/run-2026-11-20.json   # score facts gathered by hand
```

Reports land in `reports/candidates-YYYY-MM-DD.{md,csv}`, and a shareable page in `site/index.html`. Reruns skip properties already in
`data/farmscout.sqlite`; new ones are starred. Add listings you find yourself to `config/seeds.txt`.

Run it weekly with cron, e.g. `0 7 * * 1 cd ~/farmscout && farmscout run --limit 40`.

## Running on GitHub Actions

Three workflows live in `.github/workflows/`:

| Workflow | When | What it does |
| --- | --- | --- |
| `ci.yml` (Tests) | Every push and PR | Runs `pytest` |
| `scout.yml` (Scout properties) | Mondays 15:17 UTC, or **Run workflow** by hand | Searches, scores, commits `data/farmscout.sqlite` and `reports/` back to `main`, then publishes the page |
| `pages.yml` (Publish page) | After each scout run, on pushes that touch `data/`, `config/` or the page template, or by hand | Runs `farmscout report` and deploys `site/` to GitHub Pages |

One-time setup:

1. **Settings → Secrets and variables → Actions → New repository secret:** `ANTHROPIC_API_KEY`
   (optionally `BRAVE_API_KEY`).
2. **Settings → Pages → Build and deployment → Source:** *GitHub Actions*.
3. **Actions → Scout properties → Run workflow** to do the first run (try `limit` = 10).

The page is then at `https://<user>.github.io/<repo>/`. Share that link. Starred properties are saved
per browser. Note that a Pages site is public even if the repo is private (except on Enterprise plans),
and the committed database is visible to anyone who can see the repo.

To add research by hand, put a JSON list of `PropertyFacts` in a file and run
`farmscout import data/<file>.json`; commit the updated database and the page republishes.

## How it works

```
discover ──► dedupe ──► fetch ──► extract ──► enrich ──► evaluate ──► store ──► report
(sources)    (URL key)   (robots-  (Claude +   (zoning    (rule       (SQLite)  (MD, CSV)
                         aware)    regex)      class,     engine)
                                               drive time)
```

| Stage | Interface | Implementations |
| --- | --- | --- |
| Discover | `sources.base.ListingSource` | `ClaudeWebSearchSource`, `BraveSearchSource`, `SeedFileSource`, `CompositeSource` |
| Fetch | `fetching.fetcher.PageFetcher` | `HttpPageFetcher` (robots.txt, per-host delay) |
| Extract | `extraction.base.FactExtractor` | `LLMExtractor`, `HeuristicExtractor`, `LayeredExtractor` (LLM first, regex fills gaps / takes over on failure) |
| Enrich | `enrichment.enrichers.Enricher` | `ZoningClassEnricher`, `DriveTimeEnricher`, `EnrichmentChain` |
| Evaluate | `rules.base.Rule` → `rules.engine.RuleEngine` | hard gates, soft scores, penalties |
| Store | `storage.repository.CandidateRepository` | `SqliteCandidateRepository` |
| Report | `reporting.reporters.Reporter` | `MarkdownReporter`, `CsvReporter`, `SiteReporter` (shareable web page) |

`app/container.py` is the only module that picks concrete classes. Everything else depends on
the interfaces, so swapping in a new search API, a different LLM, or a Google Sheets reporter is
one new class plus one line in the container.

```
src/farmscout/
  domain/        models: RawListing, PropertyFacts, RuleOutcome, Evaluation
  config/        typed settings loaded from criteria.toml
  search/        query builder (property types × places × price cap)
  sources/       discovery adapters
  fetching/      page fetcher + HTML→text
  llm/           LLMClient interface + stdlib Claude Messages API client
  extraction/    listing text → PropertyFacts
  zoning/        zone code → commercial | mixed | farm_only | forest_only
  enrichment/    derived facts
  rules/         base classes, hard/soft/penalty rules, engine + registry
  storage/       SQLite repository, URL normalization
  reporting/     Markdown, CSV and web-page writers (templates/site.html)
  app/           composition root
  pipeline.py    orchestration
  cli.py         entry point
```

## The rules

**Hard filters** (fail = dropped; unknown = kept and flagged "to verify"):
price ≤ $1M, 5–80 acres, WA (western counties ≤ ~2 h from Seattle) or western OR.

**Soft score (0–100):**

| Rule | Points | Full credit when |
| --- | --- | --- |
| commercial_pathway | 30 | Commercial zoning, or an existing hospitality use; mixed zoning = half |
| existing_approved_use | 15 | Winery, venue, restaurant, retreat, B&B, lodge, farm stand… |
| water_supply | 10 | Water rights (well alone = 60%) |
| plunge_water | 10 | Creek, river, pond, lake, shoreline, spring |
| metro_proximity | 10 | ≤ 60 min to Seattle/Portland (county table) |
| convertible_buildings | 10 | Outbuilding ≥ 1,500 sq ft |
| commercial_kitchen | 5 | Commercial kitchen |
| extra_dwelling | 5 | 2+ dwellings |
| access | 5 | Paved road |

**Penalties:** floodplain −10, HOA −10, shared private road −5, farm/forest-only zoning with no
existing venue use −15.

To add a rule: subclass `Rule` in `rules/soft.py`, register it in `SOFT_RULES` in `rules/engine.py`,
and give it a weight in the config.

## Caveats

- **Listing sites block scrapers.** Zillow, Redfin and others disallow bots in robots.txt, and the
  fetcher respects that. For those, scoring falls back to the search snippet Claude returns, so expect
  more "to verify" items. LandSearch, LandWatch, LoopNet and brokerage sites usually expose more.
- **Zoning from listings is unreliable.** Treat the zoning score as a lead. Confirm on the county GIS
  and planning code before an offer.
- **Drive times are county-level estimates.** Edit `[drive_minutes]` to taste.
- **Cost:** each Claude search query uses up to `web_search_max_uses` searches plus tokens. 40 queries
  plus 40 extractions is a modest bill, but use `--limit` while tuning.
- The model and web-search tool versions are set in `config/criteria.toml` and
  `llm/anthropic_client.py`; update them if the API changes.

## Tests

```bash
pytest
```

Tests run offline against fixture listings and scripted LLM replies, covering rules, zoning,
extraction, sources and an end-to-end pipeline run.
