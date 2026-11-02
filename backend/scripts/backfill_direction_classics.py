"""Import curated direction classics through official publisher identities.

Reads seeds/direction_classics.csv joined with the resolver output, keeps only
records with a verifiable official landing page or formal DOI, and imports
them through the publisher path so venue confirmation and reader admission are
decided by existing services. Direction labels come from the curated seed and
are written as source='manual', which the tagging reindex never removes.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.cleaning import author_name_norm, clean_author_name, normalize_title
from app.collectors.dblp import RawPaper
from app.db import _make_engine
from app.models import Direction, Paper, PaperDirection, Venue
from app.services.publication_admission import admission_reason, nonresearch_title
from app.services.publisher_import import apply_records
from app.services.tagging import apply_tagging, load_rules, load_thresholds, load_venue_rules
from scripts.reconcile_papers import _backup

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEEDS = ROOT / "seeds" / "direction_classics.csv"
DEFAULT_RESOLVED = ROOT / "seeds" / "direction_classics_resolved.json"
DEFAULT_DATABASE = ROOT / "backend" / "data" / "papers.db"
DEFAULT_OUTPUT = ROOT / "output" / "analysis-20261102-classics" / "backfill-report.json"


def load_rows(seed_path: Path, resolved_path: Path):
    import csv

    seeds = list(csv.DictReader(seed_path.open(encoding="utf-8")))
    resolved = json.loads(resolved_path.read_text(encoding="utf-8"))["resolved"]
    metadata = {row["id"]: row for row in resolved}
    rows = []
    for seed in seeds:
        meta = metadata.get(seed["id"])
        if meta is None:
            continue
        rows.append((seed, meta))
    return rows


def prepare(seed, meta, directions):
    problems = []
    raw_title = " ".join(
        (meta.get("title") or seed["title"]).replace("{", "").replace("}", "").split()
    )
    seed_title = " ".join(seed["title"].split())
    if meta.get("source") == "arxiv":
        title = seed_title
        year = int(seed["year"])
    elif normalize_title(raw_title) == normalize_title(seed_title):
        title = seed_title
        year = int(meta.get("year") or seed["year"])
    else:
        title = raw_title
        year = int(meta.get("year") or seed["year"])
    if year < 2000:
        problems.append("pre_2000_schema_limit")
    if nonresearch_title(title):
        problems.append("nonresearch_title")
    names, seen = [], set()
    for value in meta.get("authors") or []:
        name = clean_author_name((value or "").strip())
        key = author_name_norm(name)
        if not name or not key:
            continue
        if key in seen:
            problems.append("author_multiplicity_not_representable")
            continue
        seen.add(key)
        names.append(name)
    if not names:
        problems.append("missing_authors")
    codes = [code.strip() for code in seed["directions"].split(";") if code.strip()]
    unknown = [code for code in codes if code not in directions]
    if unknown:
        problems.append("unknown_direction:" + ",".join(unknown))
    key = (meta.get("publisher_key") or meta.get("official_url") or "").strip()
    if not key.startswith("https://"):
        problems.append("missing_official_identity")
    return {
        "id": seed["id"],
        "title": title,
        "year": year,
        "venue": seed["venue"].strip(),
        "authors": names,
        "doi": (meta.get("doi") or "").strip() or None,
        "official_url": (meta.get("official_url") or "").strip() or key,
        "publisher_key": key,
        "citations": meta.get("citations"),
        "codes": codes,
        "problems": problems,
    }


def build_raw(record):
    extra = {"publisher_key": record["publisher_key"], "provenance": "manual_classic"}
    if record["citations"] is not None:
        extra["cited_by_count"] = int(record["citations"])
    return RawPaper(
        source="manual",
        venue_key="classic:" + record["id"],
        title=record["title"],
        year=record["year"],
        authors=record["authors"],
        doi=record["doi"],
        official_url=record["official_url"],
        extra=extra,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--seeds", type=Path, default=DEFAULT_SEEDS)
    parser.add_argument("--resolved", type=Path, default=DEFAULT_RESOLVED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = load_rows(args.seeds, args.resolved)
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "applied": args.apply,
        "resolved_input": len(rows),
        "pdf_downloads": 0,
    }
    try:
        with Session(engine) as db:
            directions = {row.code: row.id for row in db.query(Direction)}
            venues = {
                row.abbr: row
                for row in db.query(Venue).filter(Venue.ccf_level.in_(("A", "B")))
            }
        records, skipped = [], Counter()
        for seed, meta in rows:
            record = prepare(seed, meta, directions)
            if record["venue"] not in venues:
                record["problems"].append("venue_out_of_scope")
            if record["problems"]:
                skipped.update(record["problems"])
                record["status"] = "skipped"
                records.append(record)
                continue
            record["status"] = "selected"
            records.append(record)
        selected = [record for record in records if record["status"] == "selected"]
        report["skipped"] = dict(skipped)
        report["selected"] = len(selected)
        report["selected_by_direction"] = Counter(
            code for record in selected for code in record["codes"]
        )
        report["selected_by_direction"] = dict(report["selected_by_direction"])
        if not args.apply:
            report["records"] = records
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            print(json.dumps({"applied": False, "selected": len(selected), "skipped": report["skipped"]}, ensure_ascii=False))
            return

        report["backup"] = str(_backup(args.database.resolve()))
        by_venue = {}
        for record in selected:
            by_venue.setdefault(record["venue"], []).append(record)
        totals = Counter()
        conflicts = []
        with Session(engine) as db:
            rules, thresholds = load_rules(db), load_thresholds(db)
            venue_rules = load_venue_rules(db)
            for abbr, group in by_venue.items():
                venue = venues[abbr]
                result = apply_records(db, [build_raw(record) for record in group], venue)
                totals.update(result["counts"])
                conflicts.extend(result["conflicts"])
                for record in group:
                    paper = db.query(Paper).filter(Paper.publisher_key == record["publisher_key"]).one_or_none()
                    if paper is None:
                        record["status"] = "not_imported"
                        continue
                    record["paper_id"] = paper.id
                    record["venue_confirmed"] = paper.venue_confirmed
                    for code in record["codes"]:
                        direction_id = directions[code]
                        row = db.query(PaperDirection).filter(
                            PaperDirection.paper_id == paper.id,
                            PaperDirection.direction_id == direction_id,
                        ).one_or_none()
                        if row is None:
                            db.add(PaperDirection(
                                paper_id=paper.id, direction_id=direction_id,
                                score=2.0, source="manual",
                            ))
                        else:
                            row.source = "manual"
                            row.score = max(row.score or 0.0, 2.0)
                    db.flush()
                    apply_tagging(
                        db, paper.id, paper.title, paper.abstract, rules, thresholds,
                        venue_id=paper.venue_id, venue_rules=venue_rules,
                    )
                db.commit()
            report["import"] = dict(totals)
            report["conflicts"] = conflicts[:50]
            report["conflict_total"] = len(conflicts)

        with Session(engine) as db:
            verified, problems = [], Counter()
            for record in selected:
                paper = db.query(Paper).filter(Paper.publisher_key == record["publisher_key"]).one_or_none()
                if paper is None:
                    problems["missing_after_import"] += 1
                    record["status"] = "missing_after_import"
                    continue
                venue = db.get(Venue, paper.venue_id)
                reason = admission_reason(paper, venue)
                if reason:
                    problems[reason] += 1
                if paper.venue_confirmed != 1:
                    problems["venue_unconfirmed"] += 1
                codes = {
                    row.code
                    for row in db.query(Direction.code)
                    .join(PaperDirection, PaperDirection.direction_id == Direction.id)
                    .filter(PaperDirection.paper_id == paper.id, PaperDirection.source == "manual")
                }
                missing = [code for code in record["codes"] if code not in codes]
                if missing:
                    problems["missing_manual_tags"] += 1
                    record["missing_manual_tags"] = missing
                if not reason and not missing and paper.venue_confirmed == 1:
                    record["status"] = "verified"
                    verified.append(record["id"])
            report["verified"] = len(verified)
            report["verified_ids"] = verified
            report["verification_problems"] = dict(problems)
        report["records"] = records
    finally:
        engine.dispose()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "applied": True,
        "selected": report.get("selected"),
        "verified": report.get("verified"),
        "import": report.get("import"),
        "conflict_total": report.get("conflict_total"),
        "problems": report.get("verification_problems"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
