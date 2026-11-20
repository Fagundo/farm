# farmscout

Finds and ranks Pacific Northwest properties for a **farm + sauna + event space / farm-to-table** business.
It searches the web, reads each listing, scores it against the rules in `config/criteria.toml`,
remembers what it has already seen, and writes a ranked Markdown + CSV report.

Standard library only (Python 3.11+). Claude does the web searching and the listing reading.

## Quick start

```bash
pip install -e ".[dev]"            # or just run with PYTHONPATH=src
export ANTHROPIC_API_KEY=sk-ant-...
export RENTCAST_API_KEY=...         # optional: licensed MLS listings (what Zillow/Redfin show)
export BRAVE_API_KEY=...            # optional second search engine

farmscout queries                   # see the searches the config generates
farmscout run --limit 25            # discover + score up to 25 new properties
farmscout run --sources rentcast,redfin_csv   # just the listing feeds
farmscout evaluate https://...      # score one listing and print every rule's verdict
farmscout verify                    # check every link opens its property; catch "sold"/"pending" pages
farmscout research --mode status --top 200 --max-age-days 3   # re-confirm status, price, working link
farmscout research --top 15         # research the best candidates (status, links, zoning, water...)
farmscout report                    # rebuild reports and site/index.html from the database
farmscout import data/run-2026-11-20.json   # score facts gathered by hand
```

Reports land in `reports/candidates-YYYY-MM-DD.{md,csv}`, and a shareable page in `site/index.html`. Reruns skip properties already in
`data/farmscout.sqlite`; new ones are starred. Add listings you find yourself to `config/seeds.txt`.

Run it weekly with cron, e.g. `0 7 * * 1 cd ~/farmscout && farmscout run --limit 40`.

## Sources

| Source | Key | What it finds |
| --- | --- | --- |
| `claude` | `ANTHROPIC_API_KEY` | Open web search: land sites, brokerages, winery and venue brokers |
| `portals` | `ANTHROPIC_API_KEY` | Search restricted to zillow.com, redfin.com and realtor.com |
| `rentcast` | `RENTCAST_API_KEY` | [RentCast](https://developers.rentcast.io) licensed listings API: MLS for-sale listings filtered by state, price and lot size |
| `redfin_csv` | none | Redfin "Download All" CSV exports dropped in `data/inbox/` |
| `brave` | `BRAVE_API_KEY` | Brave Search API (optional) |
| `seeds` | none | URLs you paste into `config/seeds.txt` |

Default: `claude,portals,rentcast,redfin_csv,seeds`. A source whose key is missing is skipped with a warning.

### Zillow and Redfin

Zillow's terms of use prohibit automated queries and scraping, Redfin has no public API, and both block
bots (including GitHub's runners). So farmscout does not crawl them. It covers their listings three ways:

- **`portals`** finds Zillow, Redfin and Realtor.com listing pages through web search and scores them from
  what the search returns (price, acres, location). Expect more "to verify" items than other sources.
- **`rentcast`** pulls the same MLS listings from a licensed API. Each listing links to a web search for its
  address, which usually lands on its Zillow or Redfin page. Check RentCast's plans for request limits; a
  run uses about one request per state.
- **`redfin_csv`** reads Redfin's own export. See `data/inbox/README.md`: save a search on redfin.com, click
  **Download All**, and upload the CSV to `data/inbox/`. Pushing a CSV there starts a run.

For new-listing alerts, Zillow and Redfin saved-search emails still work; paste interesting links into
`config/seeds.txt`.

## Favoring Seattle

The search covers more than the Pacific Northwest core, but leans toward Seattle in three ways:

- **Scoring:** `home_proximity` (20 points) gives full credit within 90 minutes of Seattle, sliding to zero
  at 10 hours; anything past ~11.5 hours (`max_drive_minutes_to_home`) is out of range.
- **Searching:** each run samples places weighted by closeness, so about three quarters of queries are in
  Washington; Montana and California places still come up each run.
- **The page:** shows hours to Seattle on every property and sorts by it ("Closest to Seattle").

To add a state, add its counties to `config/counties.csv`, its code to `allowed_states`, a few places to
`[search] places`, and a RentCast area.

## Keeping links and status fresh

Listings go stale fast, and aggregator sites (homes77.com and similar) keep old copies with outdated
prices and statuses. Every scheduled run therefore:

1. **`farmscout verify`** loads each candidate's link and checks it actually shows that property (the
   street number and name appear on the page). It records `ok`, `broken`, `wrong_property` (e.g.
   redirected to a search page), `blocked` or `unreachable`, and if the page itself says sold or
   pending, updates the status (sold listings drop out).
2. **`farmscout research --mode status`** has Claude re-confirm status and price for every candidate not
   checked in 3 days, broken links first, and swap in a working MLS-mirror link (pnwresidences.com,
   coldwellbankerhomes.com, windermere.com...) that shows the current status and MLS number.
3. Full research on the top candidates, then a second `verify` to check any new links.

The page shows a link-health chip on each property, and always offers **Find on Zillow** and
**Search the web** links built from the address as a fallback.

## Research step

`farmscout research` takes the best-scoring candidates that haven't been researched in 14 days and has
Claude (with web search) look each one up beyond its listing page: other listing sites for the same
address, county assessor/GIS and zoning, FEMA flood information, water-rights records and permits. It:

- confirms the listing is still for sale (sold or withdrawn listings are ruled out; pending ones are flagged),
- finds a working listing link when the original is stale or generic (`canonical_url`; the page links to it),
- fills fields the listing left blank (zoning, water, floodplain, buildings, dwellings, county), and updates
  the price if it changed,
- records notes and the source URLs it used, shown on the page under each property.

Research only fills gaps: facts the listing states are kept, except status, price and link, which go stale.
Findings gathered by hand can be applied the same way: `farmscout research --from-file data/research-YYYY-MM-DD.json`.

## Running on GitHub Actions

Three workflows live in `.github/workflows/`:

| Workflow | When | What it does |
| --- | --- | --- |
| `ci.yml` (Tests) | Every push and PR | Runs `pytest` |
| `scout.yml` (Scout properties) | Mondays 15:17 UTC, a Redfin CSV pushed to `data/inbox/`, or **Run workflow** by hand | Searches, scores, researches the top 15, commits `data/farmscout.sqlite` and `reports/` back to `main`, then publishes the page |
| `pages.yml` (Publish page) | After each scout run, on pushes that touch `data/`, `config/` or the page template, or by hand | Runs `farmscout report` and deploys `site/` to GitHub Pages |

One-time setup:

1. **Settings → Secrets and variables → Actions → New repository secret:** `ANTHROPIC_API_KEY`
   and, if you use them, `RENTCAST_API_KEY` and `BRAVE_API_KEY`.
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
| Discover | `sources.base.ListingSource` | `ClaudeWebSearchSource` (open web and portals), `RentCastSource`, `RedfinCsvSource`, `BraveSearchSource`, `SeedFileSource`, `CompositeSource` (factories in `app/container.py`) |
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
  geo/           county table and drive-time model
  enrichment/    derived facts (zoning class, county from coordinates, drive times)
  rules/         base classes, hard/soft/penalty rules, engine + registry
  research/      researcher interface, Claude and file-replay researchers, research stage
  storage/       SQLite repository, URL normalization
  reporting/     Markdown, CSV and web-page writers (templates/site.html)
  app/           composition root
  pipeline.py    orchestration
  cli.py         entry point
```

## The rules

**Hard filters** (fail = dropped; unknown = kept and flagged "to verify"):
price ≤ $1M, 2–160 acres, a county listed in `config/counties.csv` (WA, OR, most of ID, western MT,
far northern CA), within ~11.5 h of Seattle, and not sold.

**Soft score (0–100):**

| Rule | Points | Full credit when |
| --- | --- | --- |
| commercial_pathway | 30 | Commercial zoning, or an existing hospitality use; mixed zoning = half |
| existing_approved_use | 15 | Winery, venue, restaurant, retreat, B&B, lodge, farm stand… |
| water_supply | 10 | Water rights (well alone = 60%) |
| plunge_water | 10 | Creek, river, pond, lake, shoreline, spring |
| home_proximity | 20 | ≤ 90 min to Seattle; slides to 0 at 10 h |
| metro_proximity | 5 | ≤ 60 min to the nearest city for guests (Seattle, Portland, Spokane, Boise, Missoula, Sacramento) |
| convertible_buildings | 10 | Outbuilding ≥ 1,500 sq ft |
| commercial_kitchen | 5 | Commercial kitchen |
| extra_dwelling | 5 | 2+ dwellings |
| access | 5 | Paved road |
| acreage_fit | 5 | 5–80 acres (smaller or larger gets partial credit) |

**Penalties:** floodplain −10, HOA −10, shared private road −5, farm/forest-only zoning with no
existing venue use −15.

To add a rule: subclass `Rule` in `rules/soft.py`, register it in `SOFT_RULES` in `rules/engine.py`,
and give it a weight in the config.

## Caveats

- **Listing sites block scrapers.** Zillow, Redfin and others disallow bots in robots.txt, and the
  fetcher respects that. For pages it can't read, scoring falls back to the search snippet, so expect
  more "to verify" items. RentCast and Redfin CSV rows bring their own price, acreage and location.
  LandSearch, LandWatch, LoopNet and brokerage sites usually expose more.
- **Zoning from listings is unreliable.** Treat the zoning score as a lead. Confirm on the county GIS
  and planning code before an offer.
- **Drive times are estimates**, not routed: straight-line distance × a road factor at 60 mph, from
  the property's coordinates when a source gives them (RentCast, Redfin) or its county seat otherwise,
  plus per-county penalties for ferries and slow coastal roads (`config/counties.csv`). Good for
  ranking, not for planning a trip. Change home in `[home]`.
- **Changing the criteria re-scores everything.** `farmscout report` (and every run) re-evaluates saved
  properties against the current config, so edits show up on the page at the next publish.
- **Cost:** each query is one Claude call with up to `web_search_max_uses` web searches. A default run is
  100 open-web + 60 portal queries, plus extraction for new listings and research on the top 15. Lower
  `max_queries` / `max_portal_queries` in the config, or pass `--limit`, to spend less. Each run samples a
  different slice of the ~700 type × place combinations, so a few weekly runs cover them all.
- The model and web-search tool versions are set in `config/criteria.toml` and
  `llm/anthropic_client.py`; update them if the API changes.

## Tests

```bash
pytest
```

Tests run offline against fixture listings and scripted LLM replies, covering rules, zoning,
extraction, sources and an end-to-end pipeline run.
