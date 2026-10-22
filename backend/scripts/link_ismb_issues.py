"""Associate existing papers with three publisher-identified ISMB supplements."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import _make_engine
from app.models import Venue
from app.services.ismb_associations import ISSUES, associate_issue_paper
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
    report = {
        "applied": args.apply,
        "new_papers": 0,
        "pdf_downloads": 0,
        "metadata_sha256": digest,
        "evidence_hash_basis": "Cached Crossref issue metadata, not the editorial HTML",
        "scope_basis": "Publisher editorials define each exact proceedings supplement",
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
            conference = db.query(Venue).filter_by(abbr="ISMB", type="conf").one()
            canonical = db.query(Venue).filter_by(name="Bioinformatics", type="journal").one()
            for year, issue in ISSUES.items():
                unit = {"year": year, "volume": issue["volume"], "issue": "Supplement_1",
                        "publisher_editorial": issue["editorial"], "papers": []}
                counts = Counter()
                for item in items:
                    if str(item.get("volume")) != issue["volume"]:
                        continue
                    row = {"doi": item.get("DOI"), "title": item.get("title")}
                    try:
                        with db.begin_nested():
                            link, new = associate_issue_paper(
                                db, conference, canonical, item, year, digest
                            )
                            row.update(status="new_association" if new else "existing",
                                       paper_id=link.paper_id)
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
    print(json.dumps({"applied": args.apply, "units": [
        {"year": u["year"], "counts": u["counts"]} for u in report["units"]]}))
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
