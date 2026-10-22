"""Fill missing DOI identities across populated as well as empty CCF sources.

Only configured, exact source/year identities are accepted. Reads are bounded
per source, writes are short serial transactions, and interrupted units remain
retryable. Registry exhaustion never certifies a complete publisher inventory.
"""

import argparse
import asyncio
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.filtering import PaperFilters, paper_query
from app.cleaning import normalize_doi
from app.collectors.bounded_container_search import fetch_bounded_container
from app.collectors.catalog_books import book_year
from app.collectors.catalog_conferences import conference_year
from app.collectors.crossref import (
    API,
    _fetch_inventory,
    fetch_journal,
    identify_venue,
    item_to_raw,
    journal_identities,
)
from app.collectors.http_client import make_client
from app.collectors.journal_conferences import DEDICATED, SERIES
from app.db import _make_engine
from app.models import Paper, Venue
from app.services.catalog_backfill import apply_catalog_page
from app.services.tagging import load_rules, load_thresholds
from scripts.backfill_conference_year_gaps import plan_units
from scripts.reconcile_papers import _backup


def journal_units(venues, year_from, year_to):
    """Include verified electronic and historical ISSNs without fuzzy aliases."""
    return [
        {
            "kind": "journal",
            "venue": venue.abbr,
            "issn": issn,
            "year_from": year_from,
            "year_to": year_to,
        }
        for venue in venues.values()
        if venue.type == "journal"
        for issn in sorted({issn for issn, _ in journal_identities(venue)})
    ]


def series_units(venues, year_from, year_to):
    sources = {
        abbr: issn for issn, (_, issues) in SERIES.items() for abbr in issues.values()
    }
    sources.update({abbr: spec[0] for abbr, spec in DEDICATED.items()})
    return [
        {
            "kind": "series",
            "venue": abbr,
            "issn": issn,
            "year_from": year_from,
            "year_to": year_to,
        }
        for abbr, issn in sources.items()
        if abbr in venues and venues[abbr].type == "conf"
    ]


def book_units(directory, venues, year_from, year_to):
    units = {}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text("utf8"))
        abbr = data.get("venue")
        if abbr not in venues or venues[abbr].type != "conf":
            continue
        for parent in data.get("items", []):
            year = book_year(parent, abbr)
            if (
                year is None
                or not year_from <= year <= year_to
                or not parent.get("ISBN")
            ):
                continue
            isbn = parent["ISBN"][-1]
            if not isinstance(isbn, str) or not re.fullmatch(r"[0-9X-]{10,17}", isbn):
                continue
            units[(abbr, parent["DOI"])] = {
                "kind": "book",
                "venue": abbr,
                "year": year,
                "title": parent["title"][0],
                "parent": parent,
                "exact_filter": "isbn:" + isbn,
                "discovery_file": path.name,
            }
    return list(units.values())


def eligible_item(item, venue, spec):
    """Never let a broad registry filter assign another source or imprint year."""
    doi = normalize_doi(item.get("DOI"))
    if not doi or identify_venue(item, {venue.abbr: venue}) is None:
        return False
    if spec["kind"] == "book":
        return (
            spec["title"] in (item.get("container-title") or [])
            and conference_year(item, venue) == spec["year"]
        )
    if spec["kind"] == "conference":
        return (
            item.get("container-title") == [spec["title"]]
            and conference_year(item, venue) == spec["year"]
        )
    raw = item_to_raw(item)
    return bool(raw and spec["year_from"] <= raw.year <= spec["year_to"])


def unit_key(spec):
    fields = (
        "kind",
        "venue",
        "issn",
        "year_from",
        "year_to",
        "year",
        "title",
        "exact_filter",
    )
    canonical = json.dumps({k: spec[k] for k in fields if k in spec}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def reusable_unit(old, applied):
    return (
        old.get("applied") == applied
        and old.get("status") == "registry_enumerated"
        and not old.get("counts", {}).get("identity_conflicts")
    )


def save_report(path, report):
    """Keep the previous checkpoint valid across brief Windows reader locks."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf8")
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(min(0.05 * 2**attempt, 0.4))


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing local database required")
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "report.json"
    previous = (
        json.loads(path.read_text("utf8")) if args.resume and path.exists() else {}
    )
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    with Session(engine) as db:
        venues = {
            v.abbr: v
            for v in db.query(Venue).filter(
                Venue.active == 1, Venue.ccf_level.in_(("A", "B"))
            )
        }
        if args.venue:
            unknown = set(args.venue) - set(venues)
            if unknown:
                raise ValueError(
                    "Unknown or unconfigured A/B sources: " + ", ".join(sorted(unknown))
                )
            venues = {k: v for k, v in venues.items() if k in args.venue}
        known = {
            doi
            for (doi,) in paper_query(db, PaperFilters()).with_entities(Paper.doi)
            if doi
        }
        rules, thresholds = load_rules(db), load_thresholds(db)
        db.expunge_all()
    units = journal_units(venues, args.year_from, args.year_to) if args.journals else []
    if getattr(args, "series", False):
        units.extend(series_units(venues, args.year_from, args.year_to))
    if getattr(args, "books", None):
        if not args.books.is_dir():
            raise ValueError("Existing parent-book evidence directory required")
        units.extend(book_units(args.books, venues, args.year_from, args.year_to))
    if args.discovery:
        if not args.discovery.is_dir():
            raise ValueError("Existing conference discovery directory required")
        units.extend(
            {"kind": "conference", **spec}
            for spec in plan_units(args.discovery, venues, set())
            if args.year_from <= spec["year"] <= args.year_to
        )
    units.sort(
        key=lambda u: (
            u["venue"],
            u.get("year", 0),
            u.get("issn", ""),
            u.get("title", ""),
        )
    )
    prior = {unit_key(u): u for u in previous.get("units", [])}
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "applied": args.apply,
        "pdf_downloads": 0,
        "full_coverage_verified": False,
        "requested_sources": sorted({u["venue"] for u in units}),
        "units": [],
        "planned_units": len(units),
        "status": "running",
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))

    def save():
        save_report(path, report)

    save()
    semaphore = asyncio.Semaphore(args.workers)
    try:
        async with make_client() as client:

            async def one(spec):
                async with semaphore:
                    old = prior.get(unit_key(spec), {})
                    if reusable_unit(old, args.apply):
                        report["units"].append(old)
                        save()
                        return
                    unit = {
                        **spec,
                        "applied": args.apply,
                        "status": "running",
                        "complete": False,
                        "registry_items": 0,
                        "matched_records": 0,
                        "counts": {},
                    }
                    report["units"].append(unit)
                    save()
                    stats, seen = Counter(), set()
                    venue = venues[spec["venue"]]
                    years = (
                        [spec["year"]]
                        if "year" in spec
                        else list(range(spec["year_from"], spec["year_to"] + 1))
                    )
                    with Session(engine) as db:

                        def accept(items):
                            if spec["kind"] == "book":
                                items = [
                                    {**item, "_catalog_book_parent": spec["parent"]}
                                    for item in items
                                ]
                            eligible = []
                            unit["registry_items"] += len(items)
                            for item in items:
                                doi = normalize_doi(item.get("DOI"))
                                if not eligible_item(item, venue, spec):
                                    stats["excluded_source_or_year"] += 1
                                elif doi not in seen:
                                    seen.add(doi)
                                    if doi in known:
                                        stats["already_public"] += 1
                                    else:
                                        eligible.append(item)
                            if eligible:
                                with (
                                    args.output / (unit_key(spec) + "-candidates.jsonl")
                                ).open("a", encoding="utf8") as stream:
                                    for item in eligible:
                                        stream.write(
                                            json.dumps(item, ensure_ascii=False) + "\n"
                                        )
                                if args.apply:
                                    result = apply_catalog_page(
                                        db, eligible, years, rules, thresholds
                                    )
                                    stats.update(result["counts"])
                                    if result["conflicts"]:
                                        with (args.output / "conflicts.jsonl").open(
                                            "a", encoding="utf8"
                                        ) as stream:
                                            for conflict in result["conflicts"]:
                                                stream.write(
                                                    json.dumps(
                                                        {
                                                            "venue": venue.abbr,
                                                            **conflict,
                                                        },
                                                        ensure_ascii=False,
                                                    )
                                                    + "\n"
                                                )
                                    dois = [
                                        normalize_doi(item["DOI"]) for item in eligible
                                    ]
                                    known.update(
                                        doi
                                        for (doi,) in paper_query(db, PaperFilters())
                                        .filter(Paper.doi.in_(dois))
                                        .with_entities(Paper.doi)
                                    )
                                    db.rollback()
                                else:
                                    stats["missing_candidates"] += len(eligible)
                            unit["matched_records"], unit["counts"] = (
                                len(seen),
                                dict(stats),
                            )
                            save()

                        def on_page(label, page, count, total, items):
                            unit["page"] = {
                                "source": label,
                                "number": page,
                                "seen": count,
                                "advertised": total,
                            }
                            accept(items)

                        try:
                            if spec["kind"] in ("journal", "series"):
                                await fetch_journal(
                                    client,
                                    spec["issn"],
                                    spec["year_from"],
                                    spec["year_to"],
                                    on_page=on_page,
                                )
                            elif spec["exact_filter"]:
                                try:
                                    await _fetch_inventory(
                                        client,
                                        API + "/works",
                                        spec["title"],
                                        spec["year"] - 1,
                                        spec["year"] + 1,
                                        extra_filter=spec["exact_filter"],
                                        on_page=on_page,
                                    )
                                except ValueError as error:
                                    unit["enumeration_error"] = str(error)
                                    unit["search"] = await fetch_bounded_container(
                                        client,
                                        spec["title"],
                                        spec["year"] - 1,
                                        spec["year"] + 1,
                                        on_page=accept,
                                        article_type="book-chapter"
                                        if spec["kind"] == "book"
                                        or venue.abbr in ("SODA", "SDM")
                                        else "proceedings-article",
                                    )
                            else:
                                unit["search"] = await fetch_bounded_container(
                                    client,
                                    spec["title"],
                                    spec["year"] - 1,
                                    spec["year"] + 1,
                                    on_page=accept,
                                    article_type="book-chapter"
                                    if spec["kind"] == "book"
                                    or venue.abbr in ("SODA", "SDM")
                                    else "proceedings-article",
                                )
                            unit["status"] = (
                                "bounded_search_finished"
                                if "search" in unit
                                else "registry_enumerated"
                            )
                            if stats["identity_conflicts"]:
                                unit["status"] = "partial"
                        except (
                            httpx.HTTPError,
                            ValueError,
                            KeyError,
                            TypeError,
                            OSError,
                            SQLAlchemyError,
                        ) as error:
                            db.rollback()
                            unit.update(
                                status="partial" if seen else "failed",
                                error=type(error).__name__ + ": " + str(error)[:700],
                            )
                        unit["finished_at"] = datetime.now(timezone.utc).isoformat()
                        save()
                        print(json.dumps(unit, ensure_ascii=False), flush=True)

            tasks = [asyncio.create_task(one(spec)) for spec in units]
            try:
                await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            report["status"] = "finished"
    finally:
        if report["status"] != "finished":
            report["status"] = "interrupted"
            for unit in report["units"]:
                if unit["status"] == "running":
                    unit["status"] = "interrupted"
        engine.dispose()
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--journals", action="store_true")
    parser.add_argument(
        "--series",
        action="store_true",
        help="Verified conference research tracks published as journal issues",
    )
    parser.add_argument(
        "--books",
        type=Path,
        help="Directory of official Springer parent-book discovery metadata",
    )
    parser.add_argument("--discovery", type=Path)
    parser.add_argument("--venue", action="append")
    parser.add_argument("--year-from", type=int, default=2023)
    parser.add_argument("--year-to", type=int, default=2026)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not any((args.journals, args.discovery, args.series, args.books)):
        parser.error("Choose --journals, --discovery, --series or --books")
    if (
        not 2023
        <= args.year_from
        <= args.year_to
        <= min(2026, datetime.now(timezone.utc).year)
    ):
        parser.error("Use the configured 2023–2026 publication range")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
