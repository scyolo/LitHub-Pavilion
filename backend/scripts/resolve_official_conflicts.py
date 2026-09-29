"""Resolve catalogue ambiguities using the publisher's actual citation DOI.

Dry run by default. Fetches HTML metadata only; preserves different publications.
"""
import argparse
import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.cleaning import normalize_title
from app.collectors.publisher_toc import publication_detail_doi
from app.config import settings
from app.db import _make_engine, db_file_path
from app.models import Paper, Venue
from app.services.publisher_import import apply_records, compatible_title
from scripts.audit_publications import latest_entries, official_records
from scripts.reconcile_papers import _backup, _merge_one
from scripts.reconcile_publication_versions import compatible


async def resolve(path, directory, *, apply=False):
    result = {"dry_run": not apply, "resolved": [], "conflicts": [], "pdf_downloads": 0}
    if apply:
        result["backup"] = str(_backup(path))
    entries = latest_entries(directory, "official-inventory-*.json", "units", lambda u: (u.get("venue"), u.get("year")))
    engine = _make_engine("sqlite:///" + path.resolve().as_posix())
    try:
        with Session(engine) as session:
            venues = {v.abbr: v for v in session.query(Venue)}
            async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers={"User-Agent": settings.effective_user_agent}) as client:
                for entry in entries.values():
                    if not entry.get("inventory_complete"):
                        continue
                    urls = {c["url"] for c in entry.get("conflicts", []) if c.get("url")}
                    records = await asyncio.to_thread(official_records, entry, directory)
                    venue = venues[entry["venue"]]
                    for raw in records:
                        if raw.official_url not in urls:
                            if entry["venue"] != "ICAPS" or entry["year"] != 2025:
                                continue
                            count = session.query(Paper).filter(Paper.venue_id == venue.id, Paper.title_norm == normalize_title(raw.title)).count()
                            if count < 2:
                                continue
                        try:
                            cache = directory / ("detail-" + hashlib.sha256(raw.official_url.encode()).hexdigest()[:16] + ".html")
                            if cache.exists():
                                body = cache.read_text("utf8")
                            else:
                                await asyncio.sleep(0.5)
                                response = await client.get(raw.official_url)
                                response.raise_for_status()
                                if "html" not in response.headers.get("content-type", ""):
                                    raise ValueError("Not an HTML detail page")
                                body = response.text
                                cache.write_text(body, encoding="utf8")
                            doi = publication_detail_doi(body, raw)
                            enriched = replace(raw, doi=doi)
                            hits = session.query(Paper).filter(or_(Paper.publisher_key == raw.official_url, Paper.doi == doi)).all()
                            if any(p.venue_id != venue.id or not compatible_title(p, raw) for p in hits):
                                raise ValueError("DOI owner disagrees with official title/venue")
                            if len(hits) > 2 or (len(hits) == 2 and not compatible(*hits)):
                                raise ValueError("Incompatible split strong identities")
                            ids = [p.id for p in hits]
                            if apply:
                                with session.begin_nested():
                                    if len(hits) == 2:
                                        canonical, duplicate = sorted(hits, key=lambda p: p.id)
                                        official = next(p for p in hits if p.publisher_key == raw.official_url)
                                        canonical.year = raw.year
                                        _merge_one(session, canonical, duplicate, authors_from=official)
                                outcome = apply_records(session, [enriched], venue)
                                if outcome["conflicts"]:
                                    raise ValueError(str(outcome["conflicts"]))
                            result["resolved"].append({"url": raw.official_url, "doi": doi, "ids": ids})
                        except (ValueError, httpx.HTTPError) as exc:
                            result["conflicts"].append({"url": raw.official_url, "reason": str(exc)[:300]})
            if apply:
                session.commit()
    finally:
        engine.dispose()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=db_file_path())
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(resolve(args.database, args.reports, apply=args.apply))
    path = args.reports / ("official-conflicts-applied.json" if args.apply else "official-conflicts-preview.json")
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"resolved": len(result["resolved"]), "conflicts": result["conflicts"], "report": str(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
