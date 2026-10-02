"""Read exact publisher journal issues that identify CCF conference research tracks."""

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.collectors.crossref import fetch_journal
from app.collectors.journal_conferences import DEDICATED, SERIES
from app.db import _make_engine
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
        "year_basis": "journal publication year; conference presentation year not inferred",
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
            sources = (
                SERIES
                if not args.dedicated
                else {v[0]: (v[1], {}) for v in DEDICATED.values()}
            )
            for issn, (title, issues) in sources.items():
                if args.issn and issn not in args.issn:
                    continue
                unit = {
                    "issn": issn,
                    "title": title,
                    "status": "running",
                    "counts": {},
                    "complete": False,
                }
                report["units"].append(unit)
                save()
                totals = Counter()
                try:
                    with Session(engine) as session:
                        rules, thresholds = (
                            load_rules(session),
                            load_thresholds(session),
                        )

                        def on_page(
                            label,
                            page,
                            count,
                            total,
                            items,
                            *,
                            unit=unit,
                            totals=totals,
                            rules=rules,
                            thresholds=thresholds,
                        ):
                            if args.apply:
                                result = apply_catalog_page(
                                    session,
                                    items,
                                    list(range(2023, 2027)),
                                    rules,
                                    thresholds,
                                )
                                totals.update(result["counts"])
                                if result["conflicts"]:
                                    with (args.output / "conflicts.jsonl").open(
                                        "a", encoding="utf-8"
                                    ) as stream:
                                        for conflict in result["conflicts"]:
                                            stream.write(
                                                json.dumps(conflict, ensure_ascii=False)
                                                + "\n"
                                            )
                            unit["counts"] = dict(totals)
                            unit["page"] = {
                                "label": label,
                                "page": page,
                                "seen": count,
                                "total": total,
                            }
                            save()
                            print(json.dumps(unit, ensure_ascii=False), flush=True)

                        await fetch_journal(client, issn, 2023, 2026, on_page=on_page)
                    unit["status"] = (
                        "partial"
                        if totals["identity_conflicts"]
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
                        status="partial" if totals else "failed",
                        error=f"{type(error).__name__}: {error}",
                    )
                save()
    finally:
        engine.dispose()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dedicated", action="store_true")
    p.add_argument("--issn", action="append")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
