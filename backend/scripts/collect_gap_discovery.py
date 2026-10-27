"""Collect discovery evidence (candidate containers) for explicit zero-gap venue-years.

Read-only against the corpus; writes one JSON per venue into the target
directory in the format consumed by scripts.backfill_conference_year_gaps
(--discovery). Uses the project's own discovery logic so the applied units go
through the same exact container/event/year verification as scheduled runs.
"""

import argparse
import asyncio
import io
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.collectors.conference_registry import discover_containers
from app.collectors.crossref import (
    API,
    _fetch_inventory,
)
from app.collectors.http_client import make_client
from app.db import _make_engine
from app.models import Venue
from app.ratelimit import AsyncTokenBucket


async def collect(database: Path, output: Path, wanted: dict):
    engine = _make_engine("sqlite:///" + database.resolve().as_posix())
    output.mkdir(parents=True, exist_ok=True)
    try:
        with Session(engine) as db:
            venues = {v.abbr: v for v in db.query(Venue).filter(Venue.active == 1)}
            db.expunge_all()
        limiter = AsyncTokenBucket(0.5)
        async with make_client() as client:
            for abbr, years in wanted.items():
                venue = venues.get(abbr)
                if venue is None:
                    raise ValueError(f"Unknown venue {abbr}")
                for year in years:
                    candidates, _ = await discover_containers(client, venue, year, limiter)
                    queries = []
                    for exact_filter, title in candidates.items():
                        items = await _fetch_inventory(
                            client, API + "/works", title, year - 1, year + 1,
                            extra_filter=exact_filter, max_pages=40,
                        )
                        queries.append({
                            "query": {"container": title, "filter": exact_filter},
                            "items": items,
                        })
                    doc = {"venue": abbr, "year": year, "queries": queries}
                    path = output / f"{abbr.replace(' ', '_')}-{year}.json"
                    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
                    print(json.dumps({"venue": abbr, "year": year,
                                      "containers": len(candidates),
                                      "items": sum(len(q["items"]) for q in queries),
                                      "file": str(path)}), flush=True)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--unit", action="append", required=True,
                        help="VENUE=YEAR, e.g. MobiCom=2026; repeatable")
    args = parser.parse_args()
    wanted = {}
    for spec in args.unit:
        abbr, _, year = spec.partition("=")
        wanted.setdefault(abbr.strip(), []).append(int(year))
    asyncio.run(collect(args.database, args.output, wanted))


if __name__ == "__main__":
    main()
