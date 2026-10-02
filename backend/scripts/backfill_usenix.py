"""Fetch only fixed USENIX HTML technical-session inventories, not PDF files."""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.collectors.crossref import request_with_retry
from app.collectors.usenix_catalog import SLUGS, parse_sessions, session_url
from app.db import _make_engine
from app.models import Venue
from app.services.paper_store import upsert_paper
from app.services.tagging import apply_tagging, load_rules, load_thresholds
from scripts.reconcile_papers import _backup


def apply_records(session, venue, records):
    stats = Counter()
    rules, thresholds = load_rules(session), load_thresholds(session)
    for start in range(0, len(records), 100):
        session.rollback()
        session.execute(text("PRAGMA busy_timeout=120000"))
        session.commit()
        session.execute(text("BEGIN IMMEDIATE"))
        for raw in records[start : start + 100]:
            paper, new = upsert_paper(session, raw, venue)
            apply_tagging(
                session, paper.id, paper.title, paper.abstract, rules, thresholds
            )
            note = "Official publisher published-paper inventory: " + raw.official_url
            if note not in (paper.note or ""):
                paper.note = ((paper.note + "\n") if paper.note else "") + note
            stats["new" if new else "updated"] += 1
        session.commit()
    return dict(stats)


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "report.json"
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pdf_downloads": 0,
        "full_coverage_verified": False,
        "units": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))

    def save():
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(path)

    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            for abbr in args.venue or SLUGS:
                for year in range(args.year_from, args.year_to + 1):
                    unit = {
                        "venue": abbr,
                        "year": year,
                        "status": "running",
                        "complete": False,
                    }
                    report["units"].append(unit)
                    save()
                    try:
                        url = session_url(abbr, year)
                        file = args.output / (url.split("/")[-2] + ".html")
                        if file.exists():
                            page = file.read_text(encoding="utf-8")
                        else:
                            response = await request_with_retry(client, url, attempts=4)
                            response.raise_for_status()
                            if (
                                "text/html"
                                not in response.headers.get("content-type", "")
                                or len(response.content) > 15_000_000
                            ):
                                raise ValueError(
                                    "Unexpected or oversized USENIX response"
                                )
                            page = response.text
                            file.write_text(page, encoding="utf-8")
                        records, evidence = parse_sessions(page, abbr, year)
                        unit.update(evidence)
                        unit["html_sha256"] = hashlib.sha256(page.encode()).hexdigest()
                        if args.apply:
                            with Session(engine) as session:
                                venue = (
                                    session.query(Venue)
                                    .filter_by(abbr=abbr, type="conf")
                                    .one()
                                )
                                if venue.ccf_level not in ("A", "B"):
                                    raise ValueError("Non A/B source")
                                unit["counts"] = apply_records(session, venue, records)
                        unit["status"] = "published_inventory_parsed"
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
                            error=f"{type(error).__name__}: {error}",
                        )
                    save()
                    print(json.dumps(unit, ensure_ascii=False), flush=True)
                    await asyncio.sleep(0.7)
    finally:
        engine.dispose()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--venue", action="append", choices=list(SLUGS))
    p.add_argument("--year-from", type=int, default=2023)
    p.add_argument("--year-to", type=int, default=2026)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    if not 2023 <= args.year_from <= args.year_to <= 2026:
        p.error("Supported years are 2023–2026")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
