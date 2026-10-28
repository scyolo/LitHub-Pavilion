"""Complete ICLR 2018-2022 backfill through official programmes.

The virtual-site JSON for 2019-2021 omits OpenReview forum identifiers, so
app.collectors.iclr resolves each year from an official artefact: the 2018/2019
schedule cards, the 2020 poster catalogue joined to PaperCopilot IDs, and the
2021/2022 JSON's own forum links. Every accepted main-conference poster is
applied through the publisher_toc provenance path inside the configured CCF A/B
catalogue, then automatic direction tags are recomputed. No PDF is fetched.
"""

import argparse
import asyncio
import io
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.cleaning import normalize_title
from app.collectors.http_client import make_client
from app.collectors.iclr import EXPECTED_POSTERS
from app.collectors.publisher_toc import fetch_official_inventory
from app.db import _make_engine
from app.models import Paper, Venue
from app.ratelimit import AsyncTokenBucket
from app.services.publication_admission import nonresearch_title
from app.services.publisher_import import apply_records
from app.services.tagging import apply_tagging, load_rules, load_thresholds
from scripts.reconcile_papers import _backup

YEARS = (2018, 2019, 2020, 2021, 2022)
KNOWN_FEDERATED = (
    "FedBN",
    "Dynamic Regularization",
    "HeteroFL",
    "Matched Averaging",
)


async def fetch_with_retry(client, limiter, venue, year, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            return await fetch_official_inventory(client, limiter, venue, year)
        except httpx.TransportError:
            if attempt == attempts:
                raise
            await asyncio.sleep(5 * attempt)


def _chunks(values, size=400):
    for start in range(0, len(values), size):
        yield values[start:start + size]


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
        "scope": "ICLR 2018-2022 complete accepted main-conference posters",
        "expected": {str(year): count for year, count in EXPECTED_POSTERS.items()},
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
            venue = db.query(Venue).filter(
                Venue.abbr == "ICLR",
                Venue.active == 1,
                Venue.ccf_level.in_(("A", "B")),
            ).one_or_none()
            if venue is None:
                raise ValueError("ICLR is not an active CCF A/B venue")
            report["baseline"] = {
                str(year): db.query(Paper).filter(
                    Paper.venue_id == venue.id, Paper.year == year
                ).count()
                for year in YEARS
            }
            db.expunge_all()

        selected = []
        result = None
        async with make_client() as client:
            for year in YEARS:
                if args.year and year not in args.year:
                    continue
                unit = {"year": year}
                stats = Counter()
                try:
                    records = await fetch_with_retry(client, limiter, venue, year)
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
                kept = []
                for raw in records:
                    if raw.year != year:
                        stats["year_mismatch"] += 1
                        continue
                    if not raw.authors or nonresearch_title(normalize_title(raw.title)):
                        stats["nonresearch_or_no_authors"] += 1
                        continue
                    kept.append(raw)
                stats["selected"] = len(kept)
                unit.update(status="ok", counts=dict(stats))
                if len(kept) != EXPECTED_POSTERS[year]:
                    unit["status"] = "count_mismatch"
                selected.extend(kept)
                report["units"].append(unit)
                save()
                print(json.dumps(unit, ensure_ascii=False), flush=True)

        if args.apply and selected:
            with Session(engine) as db:
                rules, thresholds = load_rules(db), load_thresholds(db)
                result = apply_records(db, selected, venue)
                keys = [
                    raw.extra["publisher_key"]
                    for raw in selected
                    if raw.extra.get("publisher_key")
                ]
                tagged = 0
                for chunk in _chunks(keys):
                    papers = db.query(Paper).filter(Paper.publisher_key.in_(chunk)).all()
                    for paper in papers:
                        apply_tagging(
                            db, paper.id, paper.title, paper.abstract, rules, thresholds
                        )
                        tagged += 1
                db.commit()
                report["import"] = result["counts"]
                report["tagged"] = tagged
                report["conflicts"] = result["conflicts"][:50]
                report["conflict_total"] = len(result["conflicts"])

        with Session(engine) as db:
            counts = {
                str(year): db.query(Paper).filter(
                    Paper.venue_id == venue.id, Paper.year == year
                ).count()
                for year in YEARS
            }
            report["coverage"] = counts
            if args.apply:
                keys = [
                    raw.extra["publisher_key"]
                    for raw in selected
                    if raw.extra.get("publisher_key")
                ]
                confirmed = 0
                unique = set()
                for chunk in _chunks(keys):
                    rows = db.query(Paper.publisher_key, Paper.venue_confirmed).filter(
                        Paper.publisher_key.in_(chunk)
                    ).all()
                    confirmed += sum(1 for _, flag in rows if flag == 1)
                    unique.update(key for key, _ in rows)
                report["verified_unique_publisher_keys"] = len(unique)
                report["verified_confirmed"] = confirmed
                report["known_federated"] = {
                    needle: db.query(Paper).filter(
                        Paper.venue_id == venue.id,
                        Paper.year.in_(YEARS),
                        Paper.title.contains(needle),
                    ).count()
                    for needle in KNOWN_FEDERATED
                }
                if not args.year:
                    report["full_coverage_verified"] = (
                        counts == {str(year): count for year, count in EXPECTED_POSTERS.items()}
                        and len(unique) == len(selected)
                        and confirmed == len(selected)
                        and not (result or {}).get("conflicts")
                    )
    finally:
        engine.dispose()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps({
        "applied": report["applied"],
        "selected": len(selected),
        "coverage": report.get("coverage"),
        "verified": report["full_coverage_verified"],
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--year", type=int, action="append")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
