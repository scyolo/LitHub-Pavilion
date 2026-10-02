"""Bounded DataCite metadata queries for exact LIPIcs conference editions."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.collectors.crossref import request_with_retry
from app.collectors.dagstuhl_catalog import SERIES, parse_record
from app.db import _make_engine
from app.models import Venue
from scripts.backfill_usenix import apply_records
from scripts.reconcile_papers import _backup


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
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            for abbr in args.venue or SERIES:
                for year in range(2023, 2027):
                    unit = {
                        "venue": abbr,
                        "year": year,
                        "status": "running",
                        "complete": False,
                    }
                    report["units"].append(unit)
                    save()
                    try:
                        query = f"id:10.4230/{SERIES[abbr]}.{year}.*"
                        result = []
                        expected = None
                        seen = set()
                        for page in range(1, 101):
                            cache = args.output / f"{abbr}-{year}-{page}.json"
                            if cache.exists():
                                body = json.loads(cache.read_text(encoding="utf-8"))
                            else:
                                response = await request_with_retry(
                                    client,
                                    "https://api.datacite.org/dois",
                                    params={
                                        "query": query,
                                        "page[size]": 100,
                                        "page[number]": page,
                                    },
                                    attempts=4,
                                )
                                response.raise_for_status()
                                body = response.json()
                                cache.write_text(
                                    json.dumps(body, ensure_ascii=False),
                                    encoding="utf-8",
                                )
                            expected = (
                                body["meta"]["total"] if expected is None else expected
                            )
                            items = body["data"]
                            for item in items:
                                if item["id"] in seen:
                                    raise ValueError("Repeated registry record")
                                seen.add(item["id"])
                                row = parse_record(item, abbr, year)
                                if row:
                                    result.append(row)
                            if len(seen) >= expected:
                                break
                            if not items:
                                raise ValueError("Truncated registry inventory")
                            await asyncio.sleep(0.6)
                        if len(seen) != expected:
                            raise ValueError("Registry inventory size mismatch")
                        unit.update(
                            registry_records=expected,
                            accepted_papers=len(result),
                            source="https://api.datacite.org/dois?query=" + query,
                        )
                        if args.apply and result:
                            with Session(engine) as session:
                                venue = (
                                    session.query(Venue)
                                    .filter_by(abbr=abbr, type="conf")
                                    .one()
                                )
                                if venue.ccf_level not in ("A", "B"):
                                    raise ValueError("Non A/B source")
                                unit["counts"] = apply_records(session, venue, result)
                        unit["status"] = (
                            "registry_enumerated" if result else "no_published_papers"
                        )
                    except (
                        httpx.HTTPError,
                        ValueError,
                        KeyError,
                        TypeError,
                        OSError,
                        SQLAlchemyError,
                    ) as e:
                        unit.update(
                            status="unresolved", error=f"{type(e).__name__}: {e}"
                        )
                    save()
                    print(json.dumps(unit, ensure_ascii=False), flush=True)
                    await asyncio.sleep(0.6)
    finally:
        engine.dispose()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--venue", action="append", choices=list(SERIES))
    p.add_argument("--apply", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
