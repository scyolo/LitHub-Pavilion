"""Audit/repair publisher years and fill DOI inventories from verified Crossref containers.

Metadata only, no PDFs, no scheduling/publication. Page caches + JSON reports
make partial runs resumable and auditable; failures never count as full coverage.
"""
import argparse
import hashlib
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.collectors.crossref import fetch_ecml, fetch_container, journal_identities, PREFIXES, fetch_journal, fetch_prefix
from app.config import settings
from app.db import _make_engine, db_file_path
from app.models import Venue, utcnow_iso
from scripts.reconcile_papers import _backup


from app.services.publisher_metadata import apply_items


async def run(args):
    path = (args.database or db_file_path()).resolve()
    if not path.is_file():
        raise ValueError("An existing SQLite database is required")
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = _backup(path)
    report = {"started_at": utcnow_iso(), "database": str(path), "backup": str(backup),
              "scope": "configured CCF A/B venues; publisher DOI inventories only", "prefixes": [],
              "full_collection_verified": False, "pdf_downloads": 0}
    engine = _make_engine("sqlite:///" + path.as_posix())
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False, headers={"User-Agent": settings.effective_user_agent}) as client:
            inventories = [(prefix, fetch_prefix) for prefix in args.prefixes]
            if args.journals:
                with Session(engine) as session:
                    journal_venues = session.query(Venue).filter(Venue.type == "journal", Venue.active == 1, Venue.ccf_level.in_(("A", "B"))).all()
                    if args.journal_abbr:
                        journal_venues = [v for v in journal_venues if v.abbr in args.journal_abbr]
                    inventories.extend((issn, fetch_journal) for issn in sorted({issn for v in journal_venues for issn, _ in journal_identities(v)}))
            if args.containers:
                inventories.extend((f'{year} IEEE International Conference on Robotics and Automation (ICRA)', fetch_container) for year in range(args.year_from, args.year_to + 1))
            if args.ecml:
                inventories.append(("ECML-PKDD", fetch_ecml))
            for prefix, fetch_inventory in inventories:
                cache_key = ('container-' + hashlib.sha256(prefix.encode()).hexdigest()[:16]) if fetch_inventory is fetch_container else prefix.replace('.', '-')
                cache = directory / f"crossref-{cache_key}-{args.year_from}-{args.year_to}.jsonl"
                marker = cache.with_suffix(".complete.json")
                items = []
                error = None
                if (marker.is_file() and cache.is_file() and not args.refresh
                        and (fetch_inventory is not fetch_journal or json.loads(marker.read_text("utf-8")).get("journal_inventory_version") == 2)):
                    items = [json.loads(line) for line in cache.read_text(encoding="utf-8").splitlines() if line]
                    if json.loads(marker.read_text(encoding="utf-8"))["count"] != len(items):
                        raise ValueError("Crossref cache count mismatch; rerun with --refresh")
                else:
                    def on_page(pfx, page, count, total, records):
                        items.extend(records)
                        with cache.open("a", encoding="utf-8") as target:
                            for record in records:
                                target.write(json.dumps(record, ensure_ascii=False) + "\n")
                        print(json.dumps({"prefix": pfx, "page": page, "received": count, "advertised": total}), flush=True)
                    cache.write_text("", encoding="utf-8")
                    if marker.exists():
                        marker.unlink()
                    try:
                        await asyncio.wait_for(fetch_inventory(client, prefix, args.year_from, args.year_to, on_page=on_page), timeout=args.timeout)
                        marker.write_text(json.dumps({"count": len(items), "collected_at": utcnow_iso(), "journal_inventory_version": 2 if fetch_inventory is fetch_journal else None}), encoding="utf-8")
                    except Exception as exc:
                        error = type(exc).__name__ + ": " + str(exc)[:300]
                with Session(engine) as session:
                    result = apply_items(session, items, range(args.year_from, args.year_to + 1))
                entry = {"prefix": prefix, "inventory_complete": error is None, "error": error, "records": len(items), "cache": str(cache), **result}
                report["prefixes"].append(entry)
                print(json.dumps({key: entry[key] for key in ("prefix", "inventory_complete", "error", "records", "counts")}), flush=True)
                (directory / f"publisher-repair-{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        with engine.connect() as connection:
            report["quick_check"] = connection.exec_driver_sql("PRAGMA quick_check").scalar()
            report["paper_count"] = connection.exec_driver_sql("SELECT count(*) FROM papers").scalar()
    finally:
        engine.dispose()
        report["finished_at"] = utcnow_iso()
        target = directory / f"publisher-repair-{stamp}.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(target), "finished_at": report["finished_at"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=db_file_path())
    parser.add_argument("--output", type=Path, default=Path("artifacts") / ("publication-audit-" + datetime.now(timezone.utc).strftime("%Y%m%d")))
    parser.add_argument("--journal-abbr", nargs="*", help="Limit journal enumeration to these configured abbreviations")
    parser.add_argument("--containers", nargs="*", choices=["ICRA"], help="Enumerate exact verified main-conference container titles")
    parser.add_argument("--ecml", action="store_true", help="Enumerate ECML-PKDD chapters with verified parent-book conference years")
    parser.add_argument("--journals", action="store_true", help="Also enumerate configured journal ISSNs")
    parser.add_argument("--prefixes", nargs="*", choices=PREFIXES, default=list(PREFIXES))
    parser.add_argument("--year-from", type=int, default=settings.startup_year_from)
    parser.add_argument("--year-to", type=int, default=settings.startup_years[-1])
    parser.add_argument("--timeout", type=int, default=600, help="Maximum network seconds per publisher prefix")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if not 2000 <= args.year_from <= args.year_to <= 2100:
        parser.error("Invalid year range")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
