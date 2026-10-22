"""Fill missing abstracts from an explicitly offered PMLR citation file.

Requires requirements-maintenance.txt. Only citation metadata is parsed; paper
records, dates, identities and nonempty abstracts remain unchanged.
"""

import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.collectors.pmlr_metadata import citation_records
from app.db import _make_engine
from app.models import Paper, Venue
from app.services.program_abstracts import fill_program_abstracts
from app.services.tagging import apply_tagging, load_rules, load_thresholds
from scripts.backfill_registry_gaps import save_report
from scripts.reconcile_papers import _backup


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--metadata", type=Path, required=True)
    p.add_argument("--source-url", required=True)
    p.add_argument("--venue", choices=("ICML", "COLT", "UAI"), required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    if (
        not args.database.is_file()
        or not args.metadata.is_file()
        or args.metadata.stat().st_size > 60000000
    ):
        p.error("Existing database and bounded citation metadata file required")
    import yaml

    content = args.metadata.read_bytes()
    items = yaml.load(content, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    records = citation_records(items, args.venue, args.year, args.source_url)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "source": args.source_url,
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "records": len(records),
        "applied": args.apply,
        "new_papers": 0,
        "pdf_downloads": 0,
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        with Session(engine) as db:
            venue = db.query(Venue).filter_by(abbr=args.venue, active=1).one()
            result = fill_program_abstracts(
                db, venue, args.year, records, args.source_url
            )
            report.update(result)
            if args.apply:
                rules, thresholds = load_rules(db), load_thresholds(db)
                for paper in db.query(Paper).filter(Paper.id.in_(result["filled"])):
                    apply_tagging(
                        db, paper.id, paper.title, paper.abstract, rules, thresholds
                    )
                db.commit()
            else:
                db.rollback()
    finally:
        engine.dispose()
    save_report(args.output / "report.json", report)
    print(
        json.dumps(
            {
                "filled": len(report["filled"]),
                "rejected": len(report["rejected"]),
                "records": len(records),
                "new_papers": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
