from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .export import export_csv
from .pipeline import run_collection
from .report import write_report
from .site import write_site
from .storage import WatchStore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "default_sources.json"
DEFAULT_DB = ROOT / "data" / "nihongo_funding_watch.sqlite3"
DEFAULT_REPORT_DIR = ROOT / "data" / "reports"
DEFAULT_SITE_DIR = ROOT / "public"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nihongo-funding-watch",
        description="Collect Japanese-language education funding, proposal, and visa news.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Fetch, store, and write today's report.")
    run.add_argument("--since-days", type=int, default=10)
    run.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)

    report = sub.add_parser("report", help="Regenerate today's report from stored items.")
    report.add_argument("--since-days", type=int, default=10)
    report.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)

    site = sub.add_parser("site", help="Regenerate browser-friendly HTML pages.")
    site.add_argument("--since-days", type=int, default=10)
    site.add_argument("--site-dir", type=Path, default=DEFAULT_SITE_DIR)

    csv = sub.add_parser("export-csv", help="Export stored items to CSV.")
    csv.add_argument("output", type=Path)

    sub.add_parser("check-duplicates", help="Check title-based duplicate groups.")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    store = WatchStore(args.db)
    store.initialize()

    if args.command == "run":
        result = run_collection(config, store, since_days=args.since_days)
        report_path = write_report(config, store, args.report_dir, since_days=args.since_days)
        print(
            f"fetched={result.fetched} stored_new={result.stored_new} "
            f"matched={result.matched} report={report_path}"
        )
        return

    if args.command == "report":
        report_path = write_report(config, store, args.report_dir, since_days=args.since_days)
        print(f"report={report_path}")
        return

    if args.command == "site":
        site_path = write_site(config, store, args.site_dir, since_days=args.since_days)
        print(f"site={site_path}")
        return

    if args.command == "export-csv":
        export_csv(store, args.output)
        print(f"csv={args.output}")
        return

    if args.command == "check-duplicates":
        duplicates = store.duplicate_groups()
        if not duplicates:
            print("duplicates=0")
            return
        print(f"duplicates={len(duplicates)}")
        for _, count, sample_title in duplicates[:30]:
            print(f"{count}\t{sample_title}")
