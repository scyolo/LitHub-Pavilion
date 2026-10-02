"""Link exact official conference issues to canonical CGF papers without duplicate rows."""

import argparse
import asyncio
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.collectors.crossref import request_with_retry
from app.collectors.eurographics_catalog import collection_identity, parse_item
from app.db import _make_engine
from app.models import PaperConference, Venue
from app.services.paper_conferences import associate_publication
from app.services.tagging import apply_tagging, load_rules, load_thresholds
from scripts.reconcile_papers import _backup


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"pdf_downloads": 0, "full_coverage_verified": False, "units": []}
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
        PaperConference.__table__.create(engine, checkfirst=True)

    def save():
        p = args.output / "report.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(p)

    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            for file in sorted(args.collections.glob("cgf-*-issues.json")):
                collections = json.loads(file.read_text(encoding="utf-8"))["_embedded"][
                    "collections"
                ]
                for collection in collections:
                    identity = collection_identity(collection)
                    if not identity:
                        continue
                    abbr, year, volume, issue = identity
                    unit = {
                        "venue": abbr,
                        "year": year,
                        "collection": collection["uuid"],
                        "status": "running",
                        "complete": False,
                        "records": 0,
                        "counts": {},
                    }
                    report["units"].append(unit)
                    save()
                    seen = set()
                    items = []
                    unavailable = 0
                    processed = 0
                    for page in range(100):
                        cache = args.output / f"{collection['uuid']}-{page}.json"
                        if cache.exists():
                            body = json.loads(cache.read_text(encoding="utf-8"))
                        else:
                            r = await request_with_retry(
                                client,
                                "https://diglib.eg.org/server/api/discover/search/objects",
                                params={
                                    "scope": collection["uuid"],
                                    "size": 100,
                                    "page": page,
                                },
                            )
                            r.raise_for_status()
                            body = r.json()
                            cache.write_text(
                                json.dumps(body, ensure_ascii=False), encoding="utf-8"
                            )
                        result = body["_embedded"]["searchResult"]
                        total = result["page"]["totalElements"]
                        for hit in result.get("_embedded", {}).get("objects", []):
                            processed += 1
                            item = hit.get("_embedded", {}).get("indexableObject")
                            if not item:
                                unavailable += 1
                                continue
                            if item["uuid"] in seen:
                                raise ValueError("Duplicate publisher item")
                            seen.add(item["uuid"])
                            items.append(item)
                        if processed >= total:
                            break
                    if processed != total:
                        raise ValueError("Incomplete official collection")
                    records = []
                    for item in items:
                        raw = parse_item(item, year, volume, issue)
                        if not raw and (
                            "dc.description.volume" not in item.get("metadata", {})
                            or "dc.description.number" not in item.get("metadata", {})
                        ):
                            uuid = item["uuid"]
                            if not re.fullmatch(r"[0-9a-f-]{36}", uuid):
                                raise ValueError("Invalid item identity")
                            owner_cache = args.output / (uuid + "-owner.json")
                            if owner_cache.exists():
                                owner = json.loads(
                                    owner_cache.read_text(encoding="utf-8")
                                )
                            else:
                                response = await request_with_retry(
                                    client,
                                    "https://diglib.eg.org/server/api/core/items/"
                                    + uuid
                                    + "/owningCollection",
                                )
                                response.raise_for_status()
                                owner = response.json()
                                owner_cache.write_text(
                                    json.dumps(owner, ensure_ascii=False),
                                    encoding="utf-8",
                                )
                            if owner.get("uuid") == collection["uuid"]:
                                raw = parse_item(
                                    item, year, volume, issue, verified_membership=True
                                )
                        if raw:
                            records.append(raw)
                    evidence = "https://diglib.eg.org/collections/" + collection["uuid"]
                    digest = hashlib.sha256(
                        json.dumps(collection, sort_keys=True).encode()
                    ).hexdigest()
                    stats = Counter()
                    unit.update(
                        records=len(records),
                        registry_items=total,
                        unavailable_records=unavailable,
                        evidence_url=evidence,
                    )
                    if args.apply:
                        with Session(engine) as session:
                            conf = session.query(Venue).filter_by(abbr=abbr).one()
                            journal = session.query(Venue).filter_by(abbr="CGF").one()
                            rules, thresholds = (
                                load_rules(session),
                                load_thresholds(session),
                            )
                            session.rollback()
                            session.execute(text("BEGIN IMMEDIATE"))
                            for raw in records:
                                try:
                                    with session.begin_nested():
                                        link, new = associate_publication(
                                            session,
                                            conf,
                                            raw,
                                            journal.id,
                                            evidence,
                                            digest,
                                        )
                                        apply_tagging(
                                            session,
                                            link.paper_id,
                                            raw.title,
                                            raw.extra.get("abstract"),
                                            rules,
                                            thresholds,
                                        )
                                        stats["linked" if new else "existing"] += 1
                                except ValueError as error:
                                    stats["conflicts"] += 1
                                    with (args.output / "conflicts.jsonl").open(
                                        "a", encoding="utf-8"
                                    ) as stream:
                                        stream.write(
                                            json.dumps(
                                                {
                                                    "venue": abbr,
                                                    "doi": raw.doi,
                                                    "title": raw.title,
                                                    "error": str(error),
                                                },
                                                ensure_ascii=False,
                                            )
                                            + "\n"
                                        )
                            session.commit()
                    unit.update(
                        counts=dict(stats),
                        status="partial"
                        if stats["conflicts"] or unavailable or (total and not records)
                        else "official_collection_linked"
                        if records
                        else "no_published_records",
                    )
                    save()
                    print(json.dumps(unit, ensure_ascii=False), flush=True)
    finally:
        engine.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--collections", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
