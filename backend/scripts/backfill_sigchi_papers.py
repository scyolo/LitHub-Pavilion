"""Cross-check public SIGCHI main-paper lists against PACMHCI formal DOI metadata.

No login or personal schedule data is used. Papers retain the publisher's issue
year; the program supplies track evidence, not a guessed publication date.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.cleaning import normalize_title
from app.collectors.crossref import item_to_raw, metadata_text, request_with_retry
from app.collectors.sigchi_program import (
    hci_title_key,
    match_hci_publication,
    program_papers,
)
from app.db import _make_engine
from app.models import Paper, Venue
from app.services.paper_store import ccf_track_eligible, upsert_paper
from app.services.tagging import apply_tagging, load_rules, load_thresholds
from scripts.reconcile_papers import _backup


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    candidates = json.loads(args.metadata.read_text(encoding="utf-8"))
    bytitle = defaultdict(list)
    for item in candidates:
        for title in item.get("title", []):
            for key in {
                normalize_title(metadata_text(title)),
                hci_title_key(title, "MobileHCI"),
            }:
                bytitle[key].append(item)
    programs = json.loads(args.program_list.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"pdf_downloads": 0, "complete": False, "applied": args.apply, "units": []}
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    path = args.output / "report.json"

    def save():
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(path)

    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            for listing in programs:
                conf = listing["conference"]
                info = listing.get("publicationInfo") or {}
                if (
                    conf.get("shortName") not in ("CSCW", "MobileHCI")
                    or conf.get("year") not in (2025, 2026)
                    or not conf.get("url")
                ):
                    continue
                if (
                    info.get("publicationStatus") != "PUBLISHED"
                    or info.get("isDraft") is not False
                ):
                    continue
                identity, version = conf.get("id"), info.get("version")
                if type(identity) is not int or type(version) is not int:
                    raise ValueError("Invalid public program identifier")
                url = f"https://files.sigchi.org/conference/cache/{identity}/{version}/program"
                unit = {
                    "venue": conf["shortName"],
                    "event_year": conf["year"],
                    "source": url,
                    "status": "running",
                    "complete": False,
                    "counts": {},
                    "unmatched": [],
                }
                report["units"].append(unit)
                save()
                try:
                    response = await request_with_retry(client, url)
                    response.raise_for_status()
                    data = response.json()
                    if len(response.content) > 20_000_000:
                        raise ValueError("Public program exceeds metadata budget")
                    if (
                        data.get("publicationInfo", {}).get("publicationStatus")
                        != "PUBLISHED"
                    ):
                        raise ValueError("Program is not published")
                    papers = program_papers(data, conf["shortName"], conf["year"])
                    digest = hashlib.sha256(response.content).hexdigest()
                    unit["program_sha256"] = digest
                    # Persist only citation/track fields, never registration or personal list data.
                    (args.output / f"{identity}-{version}-papers.json").write_text(
                        json.dumps(papers, ensure_ascii=False), encoding="utf-8"
                    )
                    matched = []
                    for paper in papers:
                        item = match_hci_publication(
                            paper, bytitle[normalize_title(paper["title"])]
                        )
                        if item:
                            matched.append((paper, item))
                        else:
                            unit["unmatched"].append(
                                {
                                    "title": paper["title"],
                                    "program_id": paper["program_id"],
                                }
                            )
                    unit["listed_papers"] = len(papers)
                    unit["matched_registry_papers"] = len(matched)
                    stats = Counter()
                    if args.apply:
                        with Session(engine) as db:
                            venue = (
                                db.query(Venue)
                                .filter_by(abbr=conf["shortName"], type="conf")
                                .one()
                            )
                            rules, thresholds = load_rules(db), load_thresholds(db)
                            for start in range(0, len(matched), 100):
                                db.rollback()
                                db.execute(text("BEGIN IMMEDIATE"))
                                for program_paper, item in matched[start : start + 100]:
                                    raw = item_to_raw(item)
                                    if raw is None:
                                        continue
                                    if (
                                        raw.publication_date
                                        and date.fromisoformat(raw.publication_date)
                                        > args.as_of
                                    ):
                                        stats["future_publication_deferred"] += 1
                                        continue
                                    try:
                                        with db.begin_nested():
                                            existing = (
                                                db.query(Paper)
                                                .filter_by(doi=raw.doi)
                                                .one_or_none()
                                            )
                                            if existing and (
                                                existing.venue_id != venue.id
                                                or normalize_title(existing.title)
                                                != normalize_title(raw.title)
                                            ):
                                                raise ValueError(
                                                    "Canonical publication identity conflict"
                                                )
                                            paper, new = upsert_paper(db, raw, venue)
                                            paper.venue_confirmed = int(
                                                ccf_track_eligible(raw, venue)
                                            )
                                            note = f"PACMHCI exact DOI/title/authors + official main-paper program: {url}; program item {program_paper['program_id']}; publication year retained, conference year {conf['year']}"
                                            if note not in (paper.note or ""):
                                                paper.note = (
                                                    (paper.note + "\n")
                                                    if paper.note
                                                    else ""
                                                ) + note
                                            apply_tagging(
                                                db,
                                                paper.id,
                                                paper.title,
                                                paper.abstract,
                                                rules,
                                                thresholds,
                                            )
                                            stats["new" if new else "updated"] += 1
                                    except ValueError as error:
                                        stats["conflicts"] += 1
                                        with (args.output / "conflicts.jsonl").open(
                                            "a", encoding="utf-8"
                                        ) as stream:
                                            stream.write(
                                                json.dumps(
                                                    {
                                                        "doi": raw.doi,
                                                        "title": raw.title,
                                                        "error": str(error),
                                                    },
                                                    ensure_ascii=False,
                                                )
                                                + "\n"
                                            )
                                db.commit()
                                unit["counts"] = dict(stats)
                                save()
                    unit["status"] = (
                        "partial"
                        if unit["unmatched"] or stats["conflicts"]
                        else "program_reconciled"
                    )
                except (
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                    TypeError,
                    OSError,
                    SQLAlchemyError,
                ) as error:
                    unit.update(status="failed", error=str(error))
                save()
                print(
                    json.dumps(
                        {k: v for k, v in unit.items() if k != "unmatched"},
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
    p.add_argument("--metadata", type=Path, required=True)
    p.add_argument("--program-list", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--as-of", type=date.fromisoformat, default=datetime.now(timezone.utc).date()
    )
    p.add_argument("--apply", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
