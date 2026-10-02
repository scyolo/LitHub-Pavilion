"""Read-only source/year coverage inventory; nonempty never means complete."""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, inspect
from sqlalchemy.orm import Session

from app.api.filtering import PaperFilters, paper_query, venue_scope
from app.models import Direction, Paper, PaperConference, PaperDirection, Venue


def build_report(db, year_from, year_to):
    years = range(year_from, year_to + 1)
    venues = (
        db.query(Venue).filter(*venue_scope(PaperFilters())).order_by(Venue.abbr).all()
    )

    def counts(include_candidates):
        query = paper_query(db, PaperFilters(), include_candidates=include_candidates)
        return {
            (venue, year): count
            for venue, year, count in query.filter(
                Paper.year.between(year_from, year_to)
            )
            .with_entities(Paper.venue_id, Paper.year, func.count(Paper.id))
            .group_by(Paper.venue_id, Paper.year)
        }

    raw, public = counts(True), counts(False)
    rows = [
        {
            "abbr": v.abbr,
            "name": v.name,
            "type": v.type,
            "level": v.ccf_level,
            "years": {
                str(y): {
                    "database_papers": raw.get((v.id, y), 0),
                    "public_papers": public.get((v.id, y), 0),
                }
                for y in years
            },
        }
        for v in venues
    ]
    empty = [
        v["abbr"]
        for v in rows
        if not any(y["public_papers"] for y in v["years"].values())
    ]
    ids = (
        paper_query(db, PaperFilters())
        .filter(Paper.year.between(year_from, year_to))
        .with_entities(Paper.id)
    )
    linked = {}
    if inspect(db.bind).has_table("paper_conferences"):
        for venue_id, year, count in (
            db.query(
                PaperConference.venue_id,
                PaperConference.event_year,
                func.count(PaperConference.paper_id),
            )
            .filter(
                PaperConference.paper_id.in_(ids),
                PaperConference.event_year.between(year_from, year_to),
            )
            .group_by(PaperConference.venue_id, PaperConference.event_year)
        ):
            linked.setdefault(venue_id, {})[str(year)] = count
    for row, venue in zip(rows, venues):
        row["associated_years"] = linked.get(venue.id, {})
    linked_empty = [
        v["abbr"] for v in rows if v["abbr"] in empty and not v["associated_years"]
    ]
    direction_counts = dict(
        db.query(PaperDirection.direction_id, func.count(PaperDirection.paper_id))
        .filter(PaperDirection.paper_id.in_(ids))
        .group_by(PaperDirection.direction_id)
        .all()
    )
    directions = [
        {"code": d.code, "name": d.name, "public_papers": direction_counts.get(d.id, 0)}
        for d in db.query(Direction)
        .filter(Direction.enabled == 1)
        .order_by(Direction.code)
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_read_only": True,
        "years": list(years),
        "configured_sources": len(venues),
        "scoped_database_papers": sum(raw.values()),
        "public_papers": sum(public.values()),
        "nonempty_public_sources": len(venues) - len(empty),
        "sources_with_direct_or_associated_papers": len(venues) - len(linked_empty),
        "empty_direct_and_associated_sources": linked_empty,
        "empty_public_sources": empty,
        "zero_public_source_year_units": sum(
            y["public_papers"] == 0 for v in rows for y in v["years"].values()
        ),
        "full_coverage_verified": False,
        "directions": directions,
        "venues": rows,
        "limitations": [
            "Nonempty source counts and exhausted registry cursors do not prove completeness.",
            "Zero source/year counts do not prove the event took place or published a proceedings.",
            "Current-year output is provisional; direction labels overlap and are not human semantic review.",
            "Database public counts may be newer than the separately exported local or deployed snapshot.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--year-from", type=int, default=2023)
    parser.add_argument("--year-to", type=int, default=2026)
    args = parser.parse_args()
    if (
        not args.database.is_file()
        or not 2000 <= args.year_from <= args.year_to <= 2100
    ):
        parser.error("Existing database and valid year range required")
    # URI read-only mode makes accidental corpus changes impossible.
    uri = args.database.resolve().as_uri() + "?mode=ro"
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    try:
        with Session(engine) as db:
            db.connection().exec_driver_sql("BEGIN")
            report = build_report(db, args.year_from, args.year_to)
    finally:
        engine.dispose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(args.output)
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k
                not in ("venues", "directions", "limitations", "empty_public_sources")
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
