"""Associate existing TECS papers with ESWEEK 2023 conference editions."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import _make_engine
from app.models import Venue
from app.services.esweek_associations import (
    EVIDENCE_URL,
    associate_issue_paper,
    session_membership,
)
from scripts.backfill_registry_gaps import save_report
from scripts.reconcile_papers import _backup


def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    evidence = args.metadata.read_bytes()
    items = json.loads(evidence)
    if not isinstance(items, list):
        raise TypeError("Cached Crossref issue metadata must be a list")
    digest = hashlib.sha256(evidence).hexdigest()
    membership = session_membership()
    report = {
        "applied": args.apply,
        "new_papers": 0,
        "pdf_downloads": 0,
        "metadata_sha256": digest,
        "evidence_url": EVIDENCE_URL,
        "evidence_hash_basis": "Cached Crossref issue metadata, not the program HTML",
        "scope_basis": (
            "Official ESWEEK 2023 session program assigns every TECS 22(5s) paper "
            "to exactly one conference; companion proceedings carry no research track"
        ),
        "publication_years_preserved": True,
        "full_coverage_verified": False,
        "units": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        with Session(engine) as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            canonical = db.query(Venue).filter_by(abbr="TECS", type="journal").one()
            for abbr in ("CODES+ISSS", "EMSOFT"):
                conference = db.query(Venue).filter_by(abbr=abbr, type="conf").one()
                unit = {
                    "venue": abbr,
                    "event_year": 2023,
                    "papers": [],
                }
                counts = Counter()
                for item in items:
                    if item.get("issue") != "5s":
                        continue
                    row = {"doi": item.get("DOI"), "title": item.get("title")}
                    try:
                        with db.begin_nested():
                            link, new = associate_issue_paper(
                                db,
                                conference,
                                canonical,
                                item,
                                membership,
                                digest,
                            )
                            row.update(
                                status="new_association" if new else "existing",
                                paper_id=link.paper_id,
                            )
                    except ValueError as error:
                        row.update(status="deferred", reason=str(error))
                    counts[row["status"]] += 1
                    unit["papers"].append(row)
                unit["counts"] = dict(counts)
                report["units"].append(unit)
            if args.apply:
                db.commit()
            else:
                db.rollback()
    finally:
        engine.dispose()
    args.output.mkdir(parents=True, exist_ok=True)
    save_report(args.output / "report.json", report)
    print(
        json.dumps(
            {
                "applied": args.apply,
                "units": [
                    {"venue": u["venue"], "counts": u["counts"]} for u in report["units"]
                ],
            }
        )
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
