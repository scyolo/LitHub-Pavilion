"""Historical federated-learning backfill through official venue catalogues (2019-2022).

Some CCF A/B venues publish outside Crossref (PMLR, OpenReview/ICLR virtual site,
papers.nips.cc, CVF open access, AAAI OJS, IJCAI/ACL/Dagstuhl sites). For those,
the scheduled pipeline already has exact-volume adapters; this maintenance unit
reuses them for 2019-2022, keeps only records whose title satisfies the
federated direction rules, and applies them with the publisher_toc provenance
path. Nothing outside the configured A/B catalogue is admitted.
"""

import argparse
import asyncio
import io
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.cleaning import normalize_title
from app.collectors.http_client import make_client
from app.collectors.publisher_toc import fetch_official_inventory
from app.db import _make_engine
from app.models import Direction, Paper, Venue
from app.ratelimit import AsyncTokenBucket
from app.services.publication_admission import nonresearch_title
from app.services.publisher_import import apply_records
from app.services.tagging import (
    apply_tagging,
    load_rules,
    load_thresholds,
    score_text,
)
from scripts.reconcile_papers import _backup

YEARS = (2019, 2020, 2021, 2022)
# Venues whose official volume adapters exist in app.collectors.publisher_toc.
VENUES = (
    "ICLR", "ICML", "NeurIPS", "CVPR", "ICCV", "AAAI", "IJCAI", "ACL", "EMNLP",
    "NAACL", "ECCV", "UAI", "COLT", "AAMAS", "KR", "ICAPS",
)


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "applied": args.apply,
        "pdf_downloads": 0,
        "full_coverage_verified": False,
        "scope": "CCF A/B official volumes; federated-learning titles; 2019-2022",
        "units": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    limiter = AsyncTokenBucket(1)

    def save():
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    try:
        with Session(engine) as db:
            venues = {
                v.abbr: v
                for v in db.query(Venue).filter(
                    Venue.active == 1, Venue.ccf_level.in_(("A", "B"))
                )
            }
            rules, thresholds = load_rules(db), load_thresholds(db)
            fed_id = db.query(Direction).filter(Direction.code == "federated").one().id
            db.expunge_all()

        async with make_client() as client:
            for abbr in VENUES:
                venue = venues.get(abbr)
                if venue is None:
                    continue
                if args.venue and abbr not in args.venue:
                    continue
                for year in YEARS:
                    unit = {"venue": abbr, "year": year}
                    stats = Counter()
                    try:
                        records = await fetch_official_inventory(client, limiter, venue, year)
                    except Exception as error:  # noqa: BLE001 - keep scanning
                        unit.update(
                            status="unavailable",
                            error=f"{type(error).__name__}: {str(error)[:160]}",
                        )
                        report["units"].append(unit)
                        save()
                        continue
                    if not records:
                        unit.update(status="no_official_volume", official=0)
                        report["units"].append(unit)
                        save()
                        continue
                    stats["official"] = len(records)
                    selected = []
                    for raw in records:
                        if raw.year != year:
                            stats["year_mismatch"] += 1
                            continue
                        if not raw.authors or nonresearch_title(normalize_title(raw.title)):
                            stats["nonresearch_or_no_authors"] += 1
                            continue
                        if (
                            score_text(rules, raw.title, None).get(fed_id, 0)
                            < thresholds[fed_id]
                        ):
                            continue
                        selected.append(raw)
                    stats["federated_candidates"] = len(selected)
                    unit.update(status="ok", counts=dict(stats))
                    if args.apply and selected:
                        with Session(engine) as db:
                            rules_now, thresholds_now = load_rules(db), load_thresholds(db)
                            result = apply_records(db, selected, venue)
                            keys = [
                                raw.extra["publisher_key"]
                                for raw in selected
                                if raw.extra.get("publisher_key")
                            ]
                            papers = db.query(Paper).filter(Paper.publisher_key.in_(keys)).all()
                            for paper in papers:
                                apply_tagging(
                                    db, paper.id, paper.title, paper.abstract,
                                    rules_now, thresholds_now,
                                )
                            db.commit()
                            unit["import"] = result["counts"]
                            unit["conflicts"] = result["conflicts"][:20]
                    report["units"].append(unit)
                    save()
                    print(json.dumps(unit, ensure_ascii=False), flush=True)
    finally:
        engine.dispose()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    total = sum(u.get("counts", {}).get("federated_candidates", 0) for u in report["units"])
    print(json.dumps({"applied": report["applied"], "federated_candidates": total}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--venue", action="append")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
