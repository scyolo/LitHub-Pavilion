"""Per-conference Springer parent-book/ISBN metadata enumeration. No book/PDF downloads."""

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.collectors.catalog_books import SPECS, book_year, chapter_year
from app.collectors.crossref import API, _fetch_inventory, request_with_retry
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
    previous = (
        json.loads(path.read_text(encoding="utf-8"))
        if args.resume and path.exists()
        else {}
    )
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pdf_downloads": 0,
        "full_coverage_verified": False,
        "applied": args.apply,
        "units": [],
    }
    if args.venue:
        report["units"] = [
            u for u in previous.get("units", []) if u["venue"] not in args.venue
        ]
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))

    def save():
        p = path.with_suffix(".tmp")
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        p.replace(path)

    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            for abbr in args.venue or SPECS:
                unit = {
                    "venue": abbr,
                    "status": "running",
                    "books": [],
                    "counts": {},
                    "complete": False,
                }
                report["units"].append(unit)
                save()
                try:
                    cache = args.output / (abbr.replace("/", "-") + "-parents.json")
                    if cache.exists():
                        parents = json.loads(cache.read_text(encoding="utf-8"))
                    else:
                        response = await request_with_retry(
                            client,
                            API + "/works",
                            params={
                                "query.title": SPECS[abbr][0],
                                "filter": "type:book,from-pub-date:2023-01-01,until-pub-date:2027-12-31",
                                "rows": 300,
                                "select": "DOI,title,subtitle,type,ISBN,published",
                            },
                            attempts=4,
                        )
                        response.raise_for_status()
                        parents = response.json()["message"]["items"]
                        cache.write_text(
                            json.dumps(parents, ensure_ascii=False), encoding="utf-8"
                        )
                    parents = {
                        p["DOI"]: p
                        for p in parents
                        if book_year(p, abbr) in range(2023, 2027)
                    }
                    totals = Counter()
                    with Session(engine) as session:
                        venue = (
                            session.query(Venue).filter_by(abbr=abbr, type="conf").one()
                        )
                        rules, thresholds = (
                            load_rules(session),
                            load_thresholds(session),
                        )
                        for doi, parent in parents.items():
                            year = book_year(parent, abbr)
                            book = {
                                "doi": doi,
                                "year": year,
                                "title": parent["title"][0],
                                "status": "running",
                                "counts": {},
                            }
                            unit["books"].append(book)
                            save()
                            old = next(
                                (
                                    b
                                    for u in previous.get("units", [])
                                    if u["venue"] == abbr
                                    for b in u.get("books", [])
                                    if b["doi"] == doi
                                    and b["status"] == "registry_enumerated"
                                ),
                                None,
                            )
                            if old and previous.get("applied") == args.apply:
                                book.update(old)
                                totals.update(old.get("counts", {}))
                                continue
                            try:
                                isbn = parent["ISBN"][-1]
                                seen = set()
                                stats = Counter()

                                def on_page(
                                    label,
                                    page,
                                    count,
                                    total,
                                    items,
                                    *,
                                    parent=parent,
                                    venue=venue,
                                    year=year,
                                    seen=seen,
                                    stats=stats,
                                    book=book,
                                    rules=rules,
                                    thresholds=thresholds,
                                ):
                                    eligible = []
                                    for original in items:
                                        item = {
                                            **original,
                                            "_catalog_book_parent": parent,
                                        }
                                        if (
                                            chapter_year(item, venue) == year
                                            and item["DOI"] not in seen
                                        ):
                                            eligible.append(item)
                                            seen.add(item["DOI"])
                                    if args.apply and eligible:
                                        result = apply_catalog_page(
                                            session, eligible, [year], rules, thresholds
                                        )
                                        stats.update(result["counts"])
                                        if result["conflicts"]:
                                            with (args.output / "conflicts.jsonl").open(
                                                "a", encoding="utf-8"
                                            ) as stream:
                                                for conflict in result["conflicts"]:
                                                    stream.write(
                                                        json.dumps(
                                                            conflict, ensure_ascii=False
                                                        )
                                                        + "\n"
                                                    )
                                    book["counts"] = dict(stats)
                                    book["accepted_chapters"] = len(seen)
                                    save()

                                await _fetch_inventory(
                                    client,
                                    API + "/works",
                                    doi,
                                    2022,
                                    2027,
                                    extra_filter="isbn:" + isbn,
                                    on_page=on_page,
                                )
                                book["status"] = (
                                    "partial"
                                    if stats["identity_conflicts"]
                                    else "registry_enumerated"
                                )
                                totals.update(stats)
                            except (
                                httpx.HTTPError,
                                ValueError,
                                KeyError,
                                TypeError,
                                OSError,
                                SQLAlchemyError,
                            ) as error:
                                book.update(
                                    status="failed",
                                    error=f"{type(error).__name__}: {error}",
                                )
                            unit["counts"] = dict(totals)
                            save()
                            print(
                                json.dumps({"venue": abbr, **book}, ensure_ascii=False),
                                flush=True,
                            )
                    unit["status"] = (
                        "registry_enumerated"
                        if parents
                        and all(
                            b["status"] == "registry_enumerated" for b in unit["books"]
                        )
                        else "partial"
                        if parents
                        else "no_verified_parent"
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
                        status="failed", error=f"{type(error).__name__}: {error}"
                    )
                save()
                print(
                    json.dumps(
                        {
                            "venue": abbr,
                            "status": unit["status"],
                            "books": len(unit["books"]),
                            "counts": unit["counts"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    finally:
        engine.dispose()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--venue", action="append", choices=list(SPECS))
    p.add_argument("--apply", action="store_true")
    p.add_argument("--resume", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
