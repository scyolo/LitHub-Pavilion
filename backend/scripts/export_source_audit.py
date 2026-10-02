"""Snapshot-bound coverage index and lazy conference/journal links; no duplicated corpus rows."""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import PaperConference, Venue
from app.services.snapshot import (
    _atomic_write,
    _json_bytes,
    _load_entry,
    manifest_revision,
)


def export_audit(db, snapshot, target):
    original = (snapshot / "manifest.json").read_bytes()
    manifest = json.loads(original)
    if manifest_revision(manifest) != manifest["revision"]:
        raise ValueError("Manifest revision mismatch")
    catalog, _ = _load_entry(snapshot, manifest["catalog"], "catalog")
    associations = (
        list(db.query(PaperConference).all())
        if inspect(db.bind).has_table("paper_conferences")
        else []
    )
    wanted = {a.paper_id for a in associations}
    papers = {}
    counts = Counter()
    years = defaultdict(Counter)
    total = 0
    for entry in manifest["chunks"]:
        rows, _ = _load_entry(snapshot, entry, "papers")
        for row in rows:
            total += 1
            if 2023 <= row["year"] <= 2026:
                counts[row["venue"]] += 1
                years[row["venue"]][str(row["year"])] += 1
            if row["id"] in wanted:
                papers[row["id"]] = row
    if total != manifest["paper_count"]:
        raise ValueError("Snapshot count mismatch")
    venues = {v.id: v for v in db.query(Venue)}
    linked = defaultdict(dict)
    for a in associations:
        p = papers.get(a.paper_id)
        venue = venues.get(a.venue_id)
        if not p or not venue or p["venue"] == venue.abbr:
            continue
        linked[venue.abbr][(p["id"], a.event_year)] = {
            "id": p["id"],
            "doi": p["doi"],
            "title": p["title"],
            "canonical_venue": p["venue"],
            "publication_year": p["year"],
            "event_year": a.event_year,
            "official_url": p["official_url"],
            "evidence_url": a.evidence_url,
        }
    target.mkdir(parents=True, exist_ok=True)
    (target / "coverage").mkdir(exist_ok=True)
    notes_path = Path(__file__).resolve().parents[2] / "seeds/source_scope_notes.json"
    notes = (
        json.loads(notes_path.read_text(encoding="utf-8")).get("sources", {})
        if notes_path.exists()
        else {}
    )
    sources = []
    for v in catalog["venues"]:
        records = list(linked[v["abbr"]].values())
        descriptor = None
        if records:
            records.sort(key=lambda r: (-r["event_year"], r["title"]))
            raw = _json_bytes(
                {
                    "version": 1,
                    "venue": v["abbr"],
                    "snapshot_revision": manifest["revision"],
                    "papers": records,
                }
            )
            sha = hashlib.sha256(raw).hexdigest()
            path = "coverage/associations-" + sha + ".json"
            _atomic_write(target / path, raw)
            descriptor = {"path": path, "sha256": sha, "count": len(records)}
        associated = len({r["id"] for r in records})
        primary = counts[v["abbr"]]
        sources.append(
            {
                "abbr": v["abbr"],
                "name": v["name"],
                "level": v["level"],
                "type": v["type"],
                "primary_count": primary,
                "primary_years": dict(years[v["abbr"]]),
                "associated_count": associated,
                "associated_years": dict(
                    Counter(str(r["event_year"]) for r in records)
                ),
                "associations": descriptor,
                "status": "indexed"
                if primary
                else "journal_linked"
                if associated
                else "unresolved",
            }
        )
    for source in sources:
        if source["status"] == "unresolved":
            source.update(
                {
                    k: v
                    for k, v in notes.get(source["abbr"], {}).items()
                    if k in {"note", "evidence_url"}
                }
            )
    index = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_revision": manifest["revision"],
        "snapshot_generated_at": manifest["generated_at"],
        "snapshot_papers": total,
        "configured_sources": len(sources),
        "direct_sources": sum(s["primary_count"] > 0 for s in sources),
        "represented_sources": sum(
            s["primary_count"] + s["associated_count"] > 0 for s in sources
        ),
        "full_coverage_verified": False,
        "sources": sources,
    }
    if (snapshot / "manifest.json").read_bytes() != original:
        raise ValueError("Snapshot changed during coverage export")
    _atomic_write(target / "source-coverage.json", _json_bytes(index))
    return index


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if not args.database.is_file():
        p.error("Existing database required")
    uri = args.database.resolve().as_uri() + "?mode=ro"
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    try:
        with Session(engine) as db:
            db.connection().exec_driver_sql("BEGIN")
            index = export_audit(db, args.snapshot, args.output)
    finally:
        engine.dispose()
    print(
        json.dumps(
            {k: v for k, v in index.items() if k != "sources"}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
