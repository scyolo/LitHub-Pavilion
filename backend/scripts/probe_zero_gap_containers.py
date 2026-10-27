"""Read-only probe: which zero-record venue-years already have publisher containers?

Uses the project's own discovery logic (discover_containers) without writing to
the database. Output is a JSON report for deciding which units can be backfilled
now versus which must remain unverified until the publisher deposits them.
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

from app.api.filtering import PaperFilters, paper_query
from app.collectors.conference_registry import discover_containers
from app.collectors.http_client import make_client
from app.db import _make_engine
from app.models import Paper, Venue
from app.ratelimit import AsyncTokenBucket


async def probe(database: Path, output: Path, venue_filter=None):
    engine = _make_engine("sqlite:///" + database.resolve().as_posix())
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "units": [],
    }
    try:
        with Session(engine) as db:
            venues = {
                v.abbr: v
                for v in db.query(Venue).filter(
                    Venue.active == 1, Venue.ccf_level.in_(("A", "B")), Venue.type == "conf"
                )
            }
            present = set(
                paper_query(db, PaperFilters())
                .with_entities(Venue.abbr, Paper.year)
                .distinct()
            )
            assoc = set(
                db.connection()
                .exec_driver_sql(
                    "select v.abbr, pc.event_year from paper_conferences pc "
                    "join venues v on v.id = pc.venue_id"
                )
                .fetchall()
            )
            db.expunge_all()
        limiter = AsyncTokenBucket(0.5)
        async with make_client() as client:
            for abbr in sorted(venues):
                if venue_filter and abbr not in venue_filter:
                    continue
                for year in (2023, 2024, 2025, 2026):
                    if (abbr, year) in present or (abbr, year) in assoc:
                        continue
                    unit = {"venue": abbr, "year": year, "status": "probing"}
                    report["units"].append(unit)
                    try:
                        candidates, scanned = await discover_containers(
                            client, venues[abbr], year, limiter
                        )
                        unit.update(
                            scanned_items=scanned,
                            containers={
                                filt: title for filt, title in candidates.items()
                            },
                            status="containers_found"
                            if candidates
                            else "no_publisher_container",
                        )
                    except Exception as error:  # noqa: BLE001 - probe must continue
                        unit.update(status="probe_error", error=f"{type(error).__name__}: {str(error)[:300]}")
                    print(json.dumps(unit, ensure_ascii=False), flush=True)
                    output.write_text(
                        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
                    )
    finally:
        engine.dispose()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {}
    for u in report["units"]:
        counts[u["status"]] = counts.get(u["status"], 0) + 1
    print(json.dumps({"counts": counts}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--venue", action="append")
    args = parser.parse_args()
    asyncio.run(probe(args.database, args.output, set(args.venue or ())))


if __name__ == "__main__":
    main()
