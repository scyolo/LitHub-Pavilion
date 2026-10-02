"""Bounded, explicit journal backfill using exact CCF A/B + ISSN + title identities.

Run with --apply to write. Crossref cursor exhaustion is NOT complete coverage
of the publisher's entire output. All requests are metadata only; no PDFs.
"""
import argparse
import asyncio
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.cleaning import normalize_title
from app.collectors.crossref import (
    API,
    fetch_journal,
    journal_identities,
    request_with_retry,
)
from app.collectors.http_client import make_client
from app.db import _make_engine
from app.models import Paper, Venue
from app.services.catalog_backfill import apply_catalog_page
from app.services.tagging import load_rules, load_thresholds
from scripts.reconcile_papers import _backup

ROOT = Path(__file__).resolve().parents[2]


def allowed_journals(seeds):
    with Path(seeds).open(encoding="utf-8-sig", newline="") as stream:
        return {v["abbr"]: v for v in csv.DictReader(stream)
                if v["type"] == "journal" and v["ccf_level"] in ("A", "B") and v["issn"]}


async def run(args):
    allowed = allowed_journals(ROOT / "seeds/venues.csv")
    names = list(dict.fromkeys(args.venue or []))
    if not args.database.is_file() or any(name not in allowed for name in names):
        raise ValueError("Existing database and configured CCF A/B journals with verified ISSNs required")
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    args.output.mkdir(parents=True, exist_ok=True)
    report_path = args.output / "report.json"
    previous = json.loads(report_path.read_text(encoding="utf-8")) if getattr(args, "resume", False) and report_path.is_file() else {}
    if getattr(args, "all_missing", False):
        with Session(engine) as session:
            present = {row[0] for row in session.query(Venue.abbr).join(Paper).distinct()}
        names = sorted(set(names) | (set(allowed) - present) | set(previous.get("requested_venues", [])))
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "scope": "CCF A/B journals only",
              "pdf_downloads": 0, "full_coverage_verified": False, "applied": args.apply,
              "requested_venues": names, "units": []}
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    def save():
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(report_path)
    save()
    try:
        async with make_client() as client:
            for name in names:
                old = next((unit for unit in previous.get("units", []) if unit["venue"] == name), None)
                if (old and old.get("status") == "registry_enumerated" and previous.get("applied") == args.apply
                        and old.get("years") == [args.year_from, args.year_to]):
                    report["units"].append(old); save(); continue
                unit = {"venue": name, "years": [args.year_from, args.year_to], "complete": False,
                        "registry_items": 0, "status": "running", "counts": {}}
                report["units"].append(unit); save()
                totals = Counter()
                try:
                    with Session(engine) as session:
                        venue = session.query(Venue).filter(Venue.abbr == name).one()
                        seed = allowed[name]
                        if venue.type != "journal" or venue.ccf_level != seed["ccf_level"] or venue.issn != seed["issn"]:
                            raise ValueError("Local venue differs from the verified A/B identity")
                        response = await request_with_retry(client, f"{API}/journals/{venue.issn}")
                        response.raise_for_status()
                        identity = response.json()["message"]
                        if (venue.issn not in identity["ISSN"]
                                or (venue.issn, normalize_title(identity["title"]).removeprefix("the ")) not in journal_identities(venue)):
                            raise ValueError("Publisher registry title/ISSN mismatch")
                        unit["source"] = f"{API}/journals/{venue.issn}/works"
                        rules, thresholds = load_rules(session), load_thresholds(session)
                        def on_page(label, page, count, total, items, *, unit=unit, rules=rules,
                                    thresholds=thresholds, totals=totals, name=name, session=session):
                            unit["registry_items"] += len(items)
                            if args.apply:
                                result = apply_catalog_page(session, items, list(range(args.year_from, args.year_to + 1)), rules, thresholds)
                                totals.update(result["counts"])
                                if result["conflicts"]:
                                    with (args.output / "conflicts.jsonl").open("a", encoding="utf-8") as stream:
                                        for conflict in result["conflicts"]:
                                            stream.write(json.dumps({"venue": name, **conflict}, ensure_ascii=False) + "\n")
                            unit["counts"] = dict(totals)
                            unit["page"] = {"filter": label, "number": page, "seen": count, "advertised": total}
                            save()
                            print(json.dumps({"venue": name, "page": unit["page"], "counts": unit["counts"]}, ensure_ascii=False), flush=True)
                        await fetch_journal(client, venue.issn, args.year_from, args.year_to, on_page=on_page, max_pages=200)
                        unit["status"] = "partial" if totals["identity_conflicts"] else "registry_enumerated"
                        unit["note"] = "Exact DOI, journal title and ISSN verified; full publisher inventory remains unverified"
                except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError, SQLAlchemyError) as error:
                    unit.update(status="partial" if unit["registry_items"] else "failed", error=f"{type(error).__name__}: {error}")
                save()
                print(json.dumps(unit, ensure_ascii=False), flush=True)
    finally:
        engine.dispose()
    return report



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--venue', action='append')
    parser.add_argument('--all-missing', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--year-from', type=int, default=2023)
    parser.add_argument('--year-to', type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.venue and not args.all_missing:
        parser.error('Choose --venue or --all-missing')
    if not 2000 <= args.year_from <= args.year_to <= datetime.now(timezone.utc).year:
        parser.error('Use a valid, non-future publication-year range')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
