"""Retry interrupted container searches with overlap-safe bounded metadata pagination."""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.collectors.bounded_container_search import fetch_bounded_container
from app.collectors.catalog_conferences import conference_year
from app.db import _make_engine
from app.models import Venue
from app.services.catalog_backfill import apply_catalog_page
from app.services.tagging import load_rules, load_thresholds
from scripts.reconcile_papers import _backup


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    units = {}
    for source in args.report:
        for unit in json.loads(source.read_text(encoding="utf-8"))["units"]:
            for part in unit.get("containers", []):
                if part.get("status") in ("partial", "failed"):
                    units[(unit["venue"], part["year"], part["title"])] = part
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"pdf_downloads": 0, "complete": False, "units": []}
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))

    def save():
        path = args.output / "report.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)

    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            for abbr, year, title in units:
                result = {
                    "venue": abbr,
                    "year": year,
                    "title": title,
                    "status": "running",
                    "complete": False,
                    "counts": {},
                }
                report["units"].append(result)
                save()
                stats = Counter()
                try:
                    with Session(engine) as session:
                        venue = (
                            session.query(Venue).filter_by(abbr=abbr, type="conf").one()
                        )
                        if venue.ccf_level not in ("A", "B"):
                            raise ValueError("Outside catalog scope")
                        rules, thresholds = (
                            load_rules(session),
                            load_thresholds(session),
                        )

                        def on_page(
                            records,
                            *,
                            venue=venue,
                            year=year,
                            stats=stats,
                            result=result,
                            rules=rules,
                            thresholds=thresholds,
                        ):
                            records = [
                                r for r in records if conference_year(r, venue) == year
                            ]
                            if args.apply:
                                applied = apply_catalog_page(
                                    session, records, [year], rules, thresholds
                                )
                                stats.update(applied["counts"])
                                if applied["conflicts"]:
                                    with (args.output / "conflicts.jsonl").open(
                                        "a", encoding="utf-8"
                                    ) as stream:
                                        for conflict in applied["conflicts"]:
                                            stream.write(
                                                json.dumps(conflict, ensure_ascii=False)
                                                + "\n"
                                            )
                            result["counts"] = dict(stats)
                            save()

                        result["search"] = await fetch_bounded_container(
                            client,
                            title,
                            year - 1,
                            year + 1,
                            on_page=on_page,
                            article_type="book-chapter"
                            if abbr in ("SODA", "SDM")
                            else "proceedings-article",
                        )
                        result["status"] = "bounded_search_finished"
                except (
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                    TypeError,
                    OSError,
                    SQLAlchemyError,
                ) as error:
                    result.update(
                        status="partial" if stats else "failed", error=str(error)
                    )
                save()
                print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        engine.dispose()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--report", type=Path, action="append", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
