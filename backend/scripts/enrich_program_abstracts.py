"""Fill blank abstracts on existing, verified CCF publications; no new papers/PDFs."""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.collectors.crossref import request_with_retry
from app.collectors.http_client import make_client
from app.db import _make_engine
from app.models import Paper, Venue
from app.services.program_abstracts import PROGRAM_HOSTS, fill_program_abstracts, program_abstracts
from app.services.tagging import apply_tagging, load_rules, load_thresholds
from scripts.backfill_registry_gaps import save_report
from scripts.reconcile_papers import _backup


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "applied": args.apply,
        "pdf_downloads": 0,
        "new_papers": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "units": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        async with make_client() as client:
            for abbr in args.venue:
                for year in range(args.year_from, args.year_to + 1):
                    # The 2026 NeurIPS meeting is still upcoming; it is not an
                    # enrichment source for published conference records yet.
                    if abbr == "NeurIPS" and year == 2026:
                        continue
                    slug = "neurips" if abbr == "NeurIPS" else abbr.lower()
                    url = f"https://{PROGRAM_HOSTS[abbr]}/static/virtual/data/{slug}-{year}-orals-posters.json"
                    unit = {
                        "venue": abbr,
                        "year": year,
                        "source": url,
                        "status": "running",
                    }
                    report["units"].append(unit)
                    save_report(args.output / "report.json", report)
                    try:
                        response = await request_with_retry(client, url, attempts=2)
                        response.raise_for_status()
                        if len(response.content) > 60_000_000:
                            raise ValueError(
                                "Program exceeds the source metadata budget"
                            )
                        records = program_abstracts(response.json(), abbr, year)
                        unit["source_sha256"] = hashlib.sha256(
                            response.content
                        ).hexdigest()
                        unit["eligible_program_records"] = len(records)
                        citation_rows = [
                            {
                                "title": r.title,
                                "authors": r.authors,
                                "year": r.year,
                                "url": r.official_url,
                                "abstract": r.extra["abstract"],
                            }
                            for r in records
                        ]
                        save_report(
                            args.output / f"{slug}-{year}-citations.json",
                            {"source": url, "papers": citation_rows},
                        )
                        with Session(engine) as db:
                            venue = db.query(Venue).filter_by(abbr=abbr, active=1).one()
                            if venue.ccf_level not in ("A", "B"):
                                raise ValueError("Outside the configured CCF scope")
                            result = fill_program_abstracts(
                                db, venue, year, records, url
                            )
                            unit.update(result)
                            if args.apply:
                                rules, thresholds = load_rules(db), load_thresholds(db)
                                for p in db.query(Paper).filter(
                                    Paper.id.in_(result["filled"])
                                ):
                                    apply_tagging(
                                        db, p.id, p.title, p.abstract, rules, thresholds
                                    )
                                db.commit()
                            else:
                                db.rollback()
                        unit["status"] = "enriched" if args.apply else "preview"
                    except (
                        httpx.HTTPError,
                        ValueError,
                        KeyError,
                        TypeError,
                        OSError,
                        SQLAlchemyError,
                    ) as error:
                        unit.update(
                            status="unresolved",
                            error=type(error).__name__ + ": " + str(error)[:600],
                        )
                    save_report(args.output / "report.json", report)
                    print(
                        json.dumps(
                            {
                                k: v
                                for k, v in unit.items()
                                if k not in ("filled", "rejected")
                            }
                            | {
                                "filled_count": len(unit.get("filled", [])),
                                "rejected_count": len(unit.get("rejected", [])),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
    finally:
        engine.dispose()
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_report(args.output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--venue", action="append", choices=tuple(PROGRAM_HOSTS))
    parser.add_argument("--year-from", type=int, default=2023)
    parser.add_argument("--year-to", type=int, default=2026)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 2023 <= args.year_from <= args.year_to <= 2026:
        parser.error("Use the agreed 2023–2026 range")
    args.venue = args.venue or ["ICML", "NeurIPS"]
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
