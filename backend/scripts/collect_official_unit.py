"""Collect explicit venue-years through the pipeline's own unit logic.

Fetches the official publisher inventory for the requested venue-year, then
ingests it exactly like a scheduled unit would (publisher_toc provenance path,
same identity checks, tagging, conflict reporting). Intended for filling an
explicitly verified zero-record gap such as an Anthology volume that went live.
"""

import argparse
import asyncio
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.collectors.http_client import make_client
from app.collectors.publisher_toc import fetch_official_inventory
from app.db import _make_engine
from app.models import Venue
from app.ratelimit import AsyncTokenBucket
from app.services.publisher_import import apply_records
from app.services.tagging import (
    apply_tagging,
    load_rules,
    load_thresholds,
)
from scripts.reconcile_papers import _backup


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "applied": args.apply,
        "pdf_downloads": 0,
        "full_coverage_verified": False,
        "units": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    limiter = AsyncTokenBucket(1)
    try:
        with Session(engine) as db:
            venue = db.query(Venue).filter_by(abbr=args.venue, active=1).one()
            unit = {"venue": args.venue, "year": args.year, "status": "running"}
            report["units"].append(unit)
            async with make_client() as client:
                official = await fetch_official_inventory(client, limiter, venue, args.year)
            unit["official_records"] = len(official)
            if not official:
                unit["status"] = "no_official_inventory"
            elif not args.apply:
                unit["status"] = "dry_run_ready"
            else:
                from app.cleaning import is_noise_title, normalize_title
                from app.models import Paper

                valid = [
                    raw
                    for raw in official
                    if raw.year == args.year
                    and not is_noise_title(normalize_title(raw.title))
                ]
                result = apply_records(db, valid, venue)
                rules, thresholds = load_rules(db), load_thresholds(db)
                keys = [raw.extra["publisher_key"] for raw in valid]
                papers = db.query(Paper).filter(Paper.publisher_key.in_(keys)).all()
                for paper in papers:
                    apply_tagging(db, paper.id, paper.title, paper.abstract, rules, thresholds)
                db.commit()
                unit.update(
                    status="partial" if result["conflicts"] else "applied",
                    counts=result["counts"],
                    conflicts=result["conflicts"][:20],
                    tagged=len(papers),
                )
    finally:
        engine.dispose()
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "applied": report["applied"],
                "units": [
                    {
                        "venue": u["venue"],
                        "year": u["year"],
                        "status": u["status"],
                        "official_records": u.get("official_records"),
                        "counts": u.get("counts", {}),
                    }
                    for u in report["units"]
                ],
            },
            ensure_ascii=False,
        )
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--venue", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
