"""Enumerate explicit alternate journal identities with independent year boundaries."""

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.cleaning import normalize_title
from app.collectors.crossref import fetch_journal, request_with_retry
from app.collectors.journal_serials import SOURCES, serial_sources, valid_serial_item
from app.db import _make_engine
from app.models import Venue
from app.services.catalog_backfill import apply_catalog_page
from app.services.tagging import load_rules, load_thresholds
from scripts.reconcile_papers import _backup


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "report.json"
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pdf_downloads": 0,
        "full_coverage_verified": False,
        "applied": args.apply,
        "units": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))

    def save():
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(path)

    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            for source in SOURCES:
                with Session(engine) as db:
                    venue = (
                        db.query(Venue)
                        .filter_by(abbr=source["venue"], type="journal")
                        .one()
                    )
                    specs = serial_sources(venue)
                    if not specs:
                        raise ValueError(
                            "Catalog identity differs from verified serial mapping"
                        )
                for spec in specs:
                    unit = {
                        "venue": source["venue"],
                        **spec,
                        "status": "running",
                        "complete": False,
                        "counts": {},
                    }
                    report["units"].append(unit)
                    save()
                    stats = Counter()
                    try:
                        identity = await request_with_retry(client, spec["registry"])
                        identity.raise_for_status()
                        identity = identity.json()["message"]
                        if (
                            normalize_title(identity["title"])
                            != normalize_title(spec["title"])
                            or spec["issn"] not in identity["ISSN"]
                        ):
                            raise ValueError("Serial registry identity mismatch")
                        with Session(engine) as db:
                            rules, thresholds = load_rules(db), load_thresholds(db)

                            def on_page(
                                label,
                                page,
                                count,
                                total,
                                items,
                                *,
                                spec=spec,
                                unit=unit,
                                stats=stats,
                                rules=rules,
                                thresholds=thresholds,
                            ):
                                eligible = [
                                    i for i in items if valid_serial_item(i, spec)
                                ]
                                stats["registry_excluded"] += len(items) - len(eligible)
                                if args.apply and eligible:
                                    result = apply_catalog_page(
                                        db,
                                        eligible,
                                        list(
                                            range(
                                                spec["year_from"], spec["year_to"] + 1
                                            )
                                        ),
                                        rules,
                                        thresholds,
                                    )
                                    stats.update(result["counts"])
                                    if result["conflicts"]:
                                        with (args.output / "conflicts.jsonl").open(
                                            "a", encoding="utf-8"
                                        ) as f:
                                            for conflict in result["conflicts"]:
                                                f.write(
                                                    json.dumps(
                                                        conflict, ensure_ascii=False
                                                    )
                                                    + "\n"
                                                )
                                unit["counts"] = dict(stats)
                                unit["page"] = {
                                    "filter": label,
                                    "number": page,
                                    "seen": count,
                                    "advertised": total,
                                }
                                save()

                            await fetch_journal(
                                client,
                                spec["issn"],
                                spec["year_from"],
                                spec["year_to"],
                                on_page=on_page,
                            )
                        unit["status"] = (
                            "partial"
                            if stats["identity_conflicts"]
                            else "registry_enumerated"
                        )
                    except (
                        httpx.HTTPError,
                        ValueError,
                        KeyError,
                        TypeError,
                        OSError,
                        SQLAlchemyError,
                    ) as error:
                        unit.update(
                            status="partial" if stats else "failed", error=str(error)
                        )
                    save()
                    print(json.dumps(unit, ensure_ascii=False), flush=True)
    finally:
        engine.dispose()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
