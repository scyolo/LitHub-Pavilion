"""Fill explicitly identified empty conference/year scopes from official registry metadata.

Nonempty scopes are not called complete. Every article is independently checked
against the configured conference name and an explicit event edition.
"""

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.filtering import PaperFilters, paper_query
from app.cleaning import normalize_doi
from app.collectors.bounded_container_search import fetch_bounded_container
from app.collectors.catalog_conferences import conference_year
from app.collectors.crossref import API, _fetch_inventory
from app.db import _make_engine
from app.models import Paper, Venue
from app.services.catalog_backfill import apply_catalog_page
from app.services.tagging import load_rules, load_thresholds
from scripts.backfill_catalog_conferences import container_filter
from scripts.reconcile_papers import _backup


def plan_units(directory, venues, present):
    units = {}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        name, year = data.get("venue"), data.get("year")
        venue = venues.get(name)
        if (
            venue is None
            or type(year) is not int
            or not 2023 <= year <= 2026
            or (name, year) in present
        ):
            continue
        for query in data.get("queries", []):
            for item in query.get("items", []):
                if conference_year(item, venue) != year:
                    continue
                title = item["container-title"][0]
                units[(name, year, title)] = {
                    "venue": name,
                    "year": year,
                    "title": title,
                    "exact_filter": container_filter(item),
                    "discovery_file": path.name,
                }
    return list(units.values())


async def run(args):
    if not args.database.is_file() or not args.discovery.is_dir():
        raise ValueError("Existing database and discovery evidence required")
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "report.json"
    previous = (
        json.loads(path.read_text(encoding="utf-8"))
        if args.resume and path.exists()
        else {}
    )
    with Session(engine) as db:
        venues = {
            v.abbr: v
            for v in db.query(Venue).filter(
                Venue.type == "conf", Venue.ccf_level.in_(("A", "B")), Venue.active == 1
            )
        }
        present = set(
            paper_query(db, PaperFilters())
            .with_entities(Venue.abbr, Paper.year)
            .distinct()
        )
        db.expunge_all()
    prior = {(u["venue"], u["year"], u["title"]): u for u in previous.get("units", [])}
    units = [
        u
        for u in plan_units(args.discovery, venues, set())
        if (u["venue"], u["year"]) not in present
        or (u["venue"], u["year"], u["title"]) in prior
    ]
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

    save()
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            for spec in units:
                old = prior.get((spec["venue"], spec["year"], spec["title"]))
                if (
                    old
                    and old.get("status")
                    in ("registry_enumerated", "bounded_search_finished")
                    and previous.get("applied") == args.apply
                ):
                    report["units"].append(old)
                    save()
                    continue
                unit = {
                    **spec,
                    "status": "running",
                    "complete": False,
                    "counts": {},
                    "matched_records": 0,
                }
                report["units"].append(unit)
                save()
                venue = venues[spec["venue"]]
                year = spec["year"]
                stats = Counter()
                seen = set()
                try:
                    with Session(engine) as db:
                        rules, thresholds = load_rules(db), load_thresholds(db)

                        def accept(
                            items,
                            *,
                            spec=spec,
                            year=year,
                            venue=venue,
                            stats=stats,
                            unit=unit,
                            seen=seen,
                            rules=rules,
                            thresholds=thresholds,
                        ):
                            eligible = []
                            for item in items:
                                doi = normalize_doi(item.get("DOI"))
                                if (
                                    doi
                                    and doi not in seen
                                    and item.get("container-title") == [spec["title"]]
                                    and conference_year(item, venue) == year
                                ):
                                    eligible.append(item)
                                    seen.add(doi)
                            if args.apply and eligible:
                                applied = apply_catalog_page(
                                    db, eligible, [year], rules, thresholds
                                )
                                stats.update(applied["counts"])
                                if applied["conflicts"]:
                                    with (args.output / "conflicts.jsonl").open(
                                        "a", encoding="utf-8"
                                    ) as stream:
                                        for conflict in applied["conflicts"]:
                                            stream.write(
                                                json.dumps(
                                                    {
                                                        "venue": spec["venue"],
                                                        "year": year,
                                                        **conflict,
                                                    },
                                                    ensure_ascii=False,
                                                )
                                                + "\n"
                                            )
                            unit["matched_records"] = len(seen)
                            unit["counts"] = dict(stats)
                            save()

                        if spec["exact_filter"]:
                            await _fetch_inventory(
                                client,
                                API + "/works",
                                spec["title"],
                                year - 1,
                                year + 1,
                                extra_filter=spec["exact_filter"],
                                on_page=lambda label, page, count, total, items: accept(
                                    items
                                ),
                            )
                            unit["status"] = (
                                "partial"
                                if stats["identity_conflicts"]
                                else "registry_enumerated"
                            )
                        else:
                            unit["search"] = await fetch_bounded_container(
                                client,
                                spec["title"],
                                year - 1,
                                year + 1,
                                on_page=accept,
                                article_type="book-chapter"
                                if spec["venue"] in ("SODA", "SDM")
                                else "proceedings-article",
                            )
                            unit["status"] = "bounded_search_finished"
                        if not seen:
                            unit["status"] = "no_verified_articles"
                except (
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                    TypeError,
                    OSError,
                    SQLAlchemyError,
                ) as error:
                    unit.update(
                        status="partial" if seen else "failed", error=str(error)
                    )
                save()
                print(json.dumps(unit, ensure_ascii=False), flush=True)
    finally:
        engine.dispose()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--discovery", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--resume", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
