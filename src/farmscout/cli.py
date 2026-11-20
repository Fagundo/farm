"""Command line entry point: ``farmscout run | evaluate | report | queries``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from farmscout.app.container import DEFAULT_SOURCES, build_pipeline
from farmscout.config.settings import Settings
from farmscout.domain.models import PropertyFacts, RawListing
from farmscout.search.query_builder import QueryBuilder


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="farmscout", description="Find and score farm/venue properties.")
    p.add_argument("--config", default="config/criteria.toml", type=Path)
    p.add_argument("--db", default="data/farmscout.sqlite", type=Path)
    p.add_argument("--reports", default="reports", type=Path)
    p.add_argument("--seeds", default="config/seeds.txt", type=Path)
    p.add_argument("--site", default="site", type=Path, help="Where the shareable web page is written")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Discover, score and report new properties")
    run.add_argument("--sources", default=",".join(DEFAULT_SOURCES),
                     help="Comma list: claude, portals, rentcast, redfin_csv, brave, seeds")
    run.add_argument("--limit", type=int, default=None, help="Max properties to evaluate this run")
    run.add_argument("--refresh", action="store_true", help="Re-evaluate properties already seen")

    ev = sub.add_parser("evaluate", help="Score specific listing URLs")
    ev.add_argument("urls", nargs="+")

    imp = sub.add_parser("import", help="Score a JSON list of PropertyFacts gathered elsewhere")
    imp.add_argument("file", type=Path)

    sub.add_parser("report", help="Rebuild reports and the web page from the database")
    sub.add_parser("queries", help="Print the search queries the config generates")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    settings = Settings.load(args.config)

    if args.cmd == "queries":
        for q in QueryBuilder(settings.search, settings.hard_filters.max_price_usd).build():
            print(q)
        return 0

    sources = args.sources.split(",") if args.cmd == "run" else ()
    pipeline = build_pipeline(settings, sources=sources, db_path=args.db,
                              reports_dir=args.reports, seeds_path=args.seeds, site_dir=args.site)

    if args.cmd == "run":
        s = pipeline.run(refresh=args.refresh, limit=args.limit)
        print(f"\nDiscovered {s.discovered}, skipped {s.skipped_seen} seen, evaluated {s.evaluated} "
              f"({s.disqualified} disqualified), {s.new} new.")
        for path in s.reports:
            print(f"Report: {path}")
    elif args.cmd == "evaluate":
        for url in args.urls:
            ev = pipeline.evaluate(RawListing(url=url, source="cli"))
            status = "DISQUALIFIED" if ev.disqualified else f"{ev.score:.0f}/100"
            print(f"\n{status}  {url}")
            for o in ev.outcomes:
                if o.reason:
                    print(f"  [{o.status.value:7}] {o.rule_id:28} {o.reason}")
    elif args.cmd == "import":
        items = [PropertyFacts.from_dict(d) for d in json.loads(args.file.read_text())]
        s = pipeline.import_facts(items)
        print(f"Imported {s.evaluated} ({s.disqualified} disqualified), {s.new} new.")
        for path in s.reports:
            print(f"Report: {path}")
    elif args.cmd == "report":
        for path in pipeline.report():
            print(f"Report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
