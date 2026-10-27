"""Targeted historical backfill of federated-learning papers (2019-2022) from CCF A/B sources.

The scheduled corpus starts in 2023, but the federated-learning direction's
foundational papers predate that window. This maintenance unit searches each
configured A/B source individually (journals by ISSN, conferences by container
name), keeps only records that pass the same exact venue/year identity checks as
scheduled collection, and requires the title to satisfy the federated direction
rules. Nothing outside the A/B catalogue is admitted; no PDFs are fetched.
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

from sqlalchemy.orm import Session  # noqa: E402

from app.cleaning import normalize_title  # noqa: E402
from app.collectors.crossref import (  # noqa: E402
    API,
    SELECT,
    identify_venue,
    item_to_raw,
    journal_identities,
    publication_date,
    request_with_retry,
)
from app.collectors.http_client import make_client  # noqa: E402
from app.db import _make_engine  # noqa: E402
from app.models import Direction, Paper, Venue  # noqa: E402
from app.ratelimit import AsyncTokenBucket  # noqa: E402
from app.services.catalog_backfill import apply_catalog_page  # noqa: E402
from app.services.publication_admission import nonresearch_title  # noqa: E402
from app.services.tagging import load_rules, load_thresholds, score_text  # noqa: E402
from scripts.reconcile_papers import _backup  # noqa: E402

YEARS = (2019, 2020, 2021, 2022)
QUERY_TERM = "federated learning"


def search_params(venue):
    """Per-source Crossref parameters; exact source identity comes later."""
    date = f"from-pub-date:{YEARS[0]}-01-01,until-pub-date:{YEARS[-1]}-12-31"
    if venue.type == "journal":
        issn = sorted({issn for issn, _ in journal_identities(venue)})[0]
        return (
            f"{API}/journals/{issn}/works",
            {"query.bibliographic": QUERY_TERM, "filter": date, "select": SELECT},
        )
    return (
        API + "/works",
        {
            "query.container-title": venue.name,
            "query.bibliographic": QUERY_TERM,
            "filter": date + ",type:proceedings-article",
            "select": SELECT,
        },
    )


async def collect_venue(client, limiter, venue, max_pages):
    endpoint, base = search_params(venue)
    items, cursor = [], ""
    for _ in range(max_pages):
        await limiter.acquire()
        params = {**base, "rows": 100}
        if cursor:
            params["cursor"] = cursor
        response = await request_with_retry(client, endpoint, params=params, attempts=4)
        response.raise_for_status()
        message = response.json()["message"]
        batch = message.get("items") or []
        items.extend(batch)
        cursor = message.get("next-cursor")
        if not batch or not cursor or len(batch) < 100:
            break
    return items


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
        "scope": "CCF A/B sources only; federated-learning titles; 2019-2022",
        "units": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    limiter = AsyncTokenBucket(1)
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
            known = {
                doi
                for (doi,) in db.query(Paper.doi).filter(Paper.doi.isnot(None)).all()
            }
            db.expunge_all()

        candidates = {}
        async with make_client() as client:
            for name in sorted(venues, key=str.lower):
                venue = venues[name]
                if args.venue and venue.abbr not in args.venue:
                    continue
                stats = Counter()
                unit = {"venue": venue.abbr, "type": venue.type}
                try:
                    items = await collect_venue(client, limiter, venue, args.max_pages)
                except Exception as error:  # noqa: BLE001 - keep scanning other sources
                    unit.update(
                        status="error",
                        error=f"{type(error).__name__}: {str(error)[:200]}",
                    )
                    report["units"].append(unit)
                    continue
                for item in items:
                    stats["scanned"] += 1
                    matched = identify_venue(item, venues)
                    if matched is None or matched.abbr != venue.abbr:
                        stats["outside_catalog"] += 1
                        continue
                    year, _ = publication_date(item)
                    if year not in YEARS:
                        stats["year_mismatch"] += 1
                        continue
                    raw = item_to_raw(item)
                    if raw is None or not raw.authors or not raw.doi:
                        stats["incomplete_metadata"] += 1
                        continue
                    if nonresearch_title(normalize_title(raw.title)):
                        stats["nonresearch"] += 1
                        continue
                    if (
                        score_text(rules, raw.title, None).get(fed_id, 0)
                        < thresholds[fed_id]
                    ):
                        stats["not_federated_title"] += 1
                        continue
                    if raw.doi in known:
                        stats["already_present"] += 1
                        continue
                    candidates[raw.doi] = item
                    stats["candidates"] += 1
                unit.update(status="ok", counts=dict(stats))
                report["units"].append(unit)
                if stats["candidates"]:
                    print(json.dumps(unit, ensure_ascii=False), flush=True)
                report["candidate_dois"] = len(candidates)
                (args.output / "report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
                )

        report["candidate_dois"] = len(candidates)
        if args.apply and candidates:
            with Session(engine) as db:
                rules, thresholds = load_rules(db), load_thresholds(db)
                result = apply_catalog_page(
                    db, list(candidates.values()), list(YEARS), rules, thresholds
                )
                report["counts"] = result["counts"]
                report["conflicts"] = result["conflicts"][:50]
        elif candidates:
            report["status"] = "dry_run"
    finally:
        engine.dispose()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "applied": report["applied"],
                "candidates": report.get("candidate_dois"),
                "counts": report.get("counts"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--venue", action="append")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
