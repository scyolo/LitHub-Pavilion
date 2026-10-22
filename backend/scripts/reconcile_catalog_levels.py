"""Reconcile explicitly selected source grades against the checked CCF catalog.

This never changes source identities, enables a source or rewrites seed settings.
Source and paper grades change atomically so public admission stays consistent.
"""

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT
from app.db import _make_engine
from app.models import Paper, Venue
from scripts.reconcile_papers import _backup


def reconcile_levels(db, seeds, provenance, names, *, apply=False):
    proposals = []
    for name in sorted(set(names)):
        seed = seeds.get(name)
        proof = provenance.get("venues", {}).get(name)
        venue = db.query(Venue).filter_by(abbr=name, active=1).one_or_none()
        if not seed or not proof or not venue:
            raise ValueError(f"Missing configured catalog source: {name}")
        if (
            seed["ccf_level"] not in {"A", "B"}
            or seed["ccf_level"] != proof.get("level")
            or seed["type"] != proof.get("type")
            or seed.get("dblp_stream") != proof.get("dblp_stream")
            or any(getattr(venue, field) != seed[field] for field in ("name", "type", "dblp_stream"))
        ):
            raise ValueError(f"Source identity or grade disagrees with catalog evidence: {name}")
        papers = db.query(Paper).filter_by(venue_id=venue.id).all()
        changed = [paper for paper in papers if paper.ccf_level != seed["ccf_level"]]
        if venue.ccf_level == seed["ccf_level"] and not changed:
            continue
        proposals.append({
            "venue": name,
            "venue_id": venue.id,
            "old_level": venue.ccf_level,
            "catalog_level": seed["ccf_level"],
            "paper_ids": [paper.id for paper in changed],
            "paper_count": len(changed),
            "catalog_pages": proof.get("pages", []),
        })
    # Validate every selected source before changing any source or paper.
    if apply:
        for proposal in proposals:
            venue = db.get(Venue, proposal["venue_id"])
            venue.ccf_level = proposal["catalog_level"]
            for paper in db.query(Paper).filter(Paper.id.in_(proposal["paper_ids"])):
                paper.ccf_level = proposal["catalog_level"]
        db.flush()
    return proposals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--venue", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("Existing database required")
    with (PROJECT_ROOT / "seeds/venues.csv").open(encoding="utf-8-sig") as stream:
        seeds = {row["abbr"]: row for row in csv.DictReader(stream)}
    raw = (PROJECT_ROOT / "seeds/ccf_catalog_provenance.json").read_bytes()
    provenance = json.loads(raw)
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "applied": args.apply,
        "catalog_edition": provenance["edition"],
        "catalog_evidence": provenance["source"],
        "catalog_provenance_sha256": hashlib.sha256(raw).hexdigest(),
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        with Session(engine) as db:
            db.execute(text("BEGIN IMMEDIATE" if args.apply else "BEGIN"))
            report["changes"] = reconcile_levels(db, seeds, provenance, args.venue, apply=args.apply)
            if args.apply:
                db.commit()
            else:
                db.rollback()
    finally:
        engine.dispose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf8")
    print(json.dumps({"applied": args.apply, "sources": len(report["changes"]),
                      "papers": sum(change["paper_count"] for change in report["changes"])}))


if __name__ == "__main__":
    main()
