"""Enumerate verified main containers, including titles not representable in Crossref filters."""

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.collectors.catalog_conferences import conference_year
from app.collectors.crossref import API, SELECT, _fetch_inventory, request_with_retry
from app.db import _make_engine
from app.models import Venue
from app.services.catalog_backfill import apply_catalog_page
from app.services.tagging import load_rules, load_thresholds
from scripts.backfill_catalog_conferences import container_filter
from scripts.reconcile_papers import _backup

QUERIES = {
    "HOT CHIPS": "{year} IEEE Hot Chips Symposium HCS",
    "CCS": "ACM SIGSAC Conference on Computer and Communications Security",
    "DAC": "ACM IEEE Design Automation Conference",
    "SIGCOMM": "ACM SIGCOMM Conference",
    "S&P": "{year} IEEE Symposium on Security and Privacy (SP)",
    "SIGGRAPH": "ACM SIGGRAPH {year} Conference Papers",
    "HotOS": "Workshop on Hot Topics in Operating Systems",
    "CSFW": "IEEE Computer Security Foundations Symposium CSF",
    "DATE": "Design Automation Test Europe Conference Exhibition DATE",
    "I3D": "Symposium on Interactive 3D Graphics and Games I3D",
    "IWQoS": "IEEE ACM International Symposium on Quality of Service",
    "CODES+ISSS": "International Conference on Hardware Software Codesign and System Synthesis",
    "NOSSDAV": "Workshop on Network and Operating System Support for Digital Audio and Video",
    "FSE": "ACM International Conference on the Foundations of Software Engineering",
    "ICWSM": "Proceedings of the International AAAI Conference on Web and Social Media",
}


class EndOfContainerSearch(Exception):
    """A relevance-sorted bounded search reached a page without target records."""


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "report.json"
    old = (
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
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))

    def save():
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(path)

    evidence = {}
    for file in args.discovery.glob("*.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        evidence[data["venue"]] = [
            i for q in data["queries"] for i in q.get("items", [])
        ]
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            with Session(engine) as session:
                venues = (
                    session.query(Venue)
                    .filter(Venue.type == "conf", Venue.ccf_level.in_(("A", "B")))
                    .all()
                )
                session.expunge_all()
            for venue in venues:
                if args.venue and venue.abbr not in args.venue:
                    continue
                candidates = evidence.get(venue.abbr, [])
                if venue.abbr in QUERIES:
                    for year in range(2023, 2027):
                        cache = args.output / (
                            venue.abbr.replace("/", "-") + f"-{year}-query.json"
                        )
                        try:
                            if cache.exists():
                                items = json.loads(cache.read_text(encoding="utf-8"))
                            else:
                                r = await request_with_retry(
                                    client,
                                    API + "/works",
                                    params={
                                        "query.container-title": QUERIES[venue.abbr].format(year=year),
                                        "filter": f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31" + (",type:proceedings-article" if venue.abbr != "ICWSM" else ""),
                                        "rows": 300,
                                        "select": SELECT + ",ISBN",
                                    },
                                    attempts=4,
                                )
                                r.raise_for_status()
                                items = r.json()["message"]["items"]
                                cache.write_text(
                                    json.dumps(items, ensure_ascii=False),
                                    encoding="utf-8",
                                )
                            candidates.extend(items)
                        except (
                            httpx.HTTPError,
                            ValueError,
                            KeyError,
                            TypeError,
                            OSError,
                            SQLAlchemyError,
                        ) as e:
                            print(venue.abbr, "discovery", type(e).__name__, flush=True)
                containers = {}
                for item in candidates:
                    year = conference_year(item, venue)
                    if year in range(2023, 2027):
                        containers[(item["container-title"][0], year)] = item
                if not containers:
                    if args.venue:
                        report["units"].append({"venue":venue.abbr,"status":"no_verified_container","containers":[],"counts":{},"complete":False});save()
                    continue
                unit = {
                    "venue": venue.abbr,
                    "status": "running",
                    "complete": False,
                    "containers": [],
                    "counts": {},
                }
                report["units"].append(unit)
                save()
                totals = Counter()
                with Session(engine) as session:
                    rules, thresholds = load_rules(session), load_thresholds(session)
                    for (title, year), sample in containers.items():
                        part = {
                            "title": title,
                            "year": year,
                            "status": "running",
                            "counts": {},
                        }
                        unit["containers"].append(part)
                        save()
                        previous = next(
                            (
                                p
                                for u in old.get("units", [])
                                if u["venue"] == venue.abbr
                                for p in u["containers"]
                                if p["title"] == title
                                and p["year"] == year
                                and p["status"]
                                in ("registry_enumerated", "bounded_registry_search")
                            ),
                            None,
                        )
                        if previous and old.get("applied") == args.apply:
                            part.update(previous)
                            totals.update(part["counts"])
                            continue
                        stats = Counter()
                        seen = set()
                        uses_query = container_filter(sample) is None

                        def on_page(
                            label,
                            page,
                            count,
                            total,
                            records,
                            *,
                            venue=venue,
                            year=year,
                            title=title,
                            part=part,
                            seen=seen,
                            stats=stats,
                            uses_query=uses_query,
                            rules=rules,
                            thresholds=thresholds,
                        ):
                            eligible = []
                            for item in records:
                                if (
                                    item.get("container-title") == [title]
                                    and conference_year(item, venue) == year
                                    and item["DOI"] not in seen
                                ):
                                    eligible.append(item)
                                    seen.add(item["DOI"])
                            if uses_query and not eligible:
                                raise EndOfContainerSearch()
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
                                                json.dumps(conflict, ensure_ascii=False)
                                                + "\n"
                                            )
                            part["counts"] = dict(stats)
                            part["accepted_papers"] = len(seen)
                            save()

                        exact = container_filter(sample)
                        try:
                            await _fetch_inventory(
                                client,
                                API + "/works",
                                title,
                                year - 1,
                                year + 1,
                                on_page=on_page,
                                extra_filter=exact
                                or (
                                    "type:book-chapter"
                                    if venue.abbr in ("SODA", "SDM")
                                    else "type:proceedings-article"
                                ),
                                query=None
                                if exact
                                else {"query.container-title": title},
                                max_pages=200 if exact else 10,
                            )
                            part["status"] = (
                                "registry_enumerated"
                                if exact
                                else "bounded_registry_search"
                            )
                        except EndOfContainerSearch:
                            part["status"] = "bounded_registry_search"
                        except (
                            httpx.HTTPError,
                            ValueError,
                            KeyError,
                            TypeError,
                            OSError,
                            SQLAlchemyError,
                        ) as error:
                            part.update(
                                status="partial" if seen else "failed",
                                error=f"{type(error).__name__}: {error}",
                            )
                        totals.update(stats)
                        unit["counts"] = dict(totals)
                        save()
                        print(
                            json.dumps(
                                {"venue": venue.abbr, **part}, ensure_ascii=False
                            ),
                            flush=True,
                        )
                unit["status"] = (
                    "partial"
                    if any(
                        p["status"] in ("partial", "failed") for p in unit["containers"]
                    )
                    else "containers_processed"
                )
                save()
    finally:
        engine.dispose()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--discovery", type=Path, required=True)
    p.add_argument("--venue", action="append")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--resume", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
