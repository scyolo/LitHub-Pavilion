"""Reconcile official CoNEXT/PODS research lists to their journal-published records."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.cleaning import normalize_title
from app.collectors.crossref import item_to_raw, metadata_text
from app.collectors.joint_journal_lists import (
    match_registry_paper,
    parse_publication_list,
)
from app.db import _make_engine
from app.models import Venue
from app.services.listed_journal_papers import store_listed_paper
from app.services.tagging import apply_tagging, load_rules, load_thresholds
from scripts.reconcile_papers import _backup

CONFIGS = [
    (
        "PODS",
        2025,
        "pods2025-list.html",
        "PACMMOD-metadata.json",
        "https://2025.sigmod.org/pods_papers.shtml",
    ),
    (
        "CoNEXT",
        2023,
        "conext23-accepted.html",
        "PACMNET-metadata.json",
        "https://conferences2.sigcomm.org/co-next/2023/partials/accepted-papers.html",
    ),
    (
        "PODS",
        2024,
        "pods2024-list.txt",
        "PACMMOD-metadata.json",
        "https://2024.sigmod.org/pods_list.shtml",
    ),
]


def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"pdf_downloads": 0, "complete": False, "applied": args.apply, "units": []}
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        for abbr, year, filename, metadata_name, url in CONFIGS:
            html = (args.evidence / filename).read_text(encoding="utf-8")
            papers = parse_publication_list(html, abbr, year)
            items = json.loads(
                (args.evidence / metadata_name).read_text(encoding="utf-8")
            )
            bytitle = defaultdict(list)
            for item in items:
                for title in item.get("title", []):
                    bytitle[normalize_title(metadata_text(title))].append(item)
            unit = {
                "venue": abbr,
                "year": year,
                "source": url,
                "source_sha256": hashlib.sha256(html.encode()).hexdigest(),
                "complete": False,
                "listed_papers": len(papers),
                "papers": [],
            }
            stats = Counter()
            with Session(engine) as db:
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                venue = db.query(Venue).filter_by(abbr=abbr, type="conf").one()
                rules, thresholds = load_rules(db), load_thresholds(db)
                for listed in papers:
                    outcome = {"title": listed["title"]}
                    item = match_registry_paper(
                        listed, bytitle[normalize_title(listed["title"])], abbr
                    )
                    if not item:
                        outcome["status"] = "unresolved_identity"
                    else:
                        raw = item_to_raw(item)
                        if (
                            raw.publication_date
                            and date.fromisoformat(raw.publication_date) > args.as_of
                        ):
                            outcome["status"] = "future_publication_deferred"
                        else:
                            try:
                                with db.begin_nested():
                                    p, new, corrected = store_listed_paper(
                                        db, venue, item, url, year
                                    )
                                    apply_tagging(
                                        db, p.id, p.title, p.abstract, rules, thresholds
                                    )
                                    outcome.update(
                                        status="matched",
                                        paper_id=p.id,
                                        doi=p.doi,
                                        new=new,
                                        source_corrected=corrected,
                                    )
                                    stats["new" if new else "existing"] += 1
                                    stats["source_corrected"] += int(corrected)
                            except ValueError as error:
                                outcome.update(
                                    status="identity_conflict", error=str(error)
                                )
                    stats[outcome["status"]] += 1
                    unit["papers"].append(outcome)
                if args.apply:
                    db.commit()
                else:
                    db.rollback()
            unit["counts"] = dict(stats)
            report["units"].append(unit)
            path = args.output / "report.json"
            temp = path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temp.replace(path)
            print(
                json.dumps(
                    {
                        "venue": abbr,
                        "year": year,
                        "counts": dict(stats),
                        "complete": False,
                    }
                ),
                flush=True,
            )
    finally:
        engine.dispose()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    p.add_argument("--apply", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()
