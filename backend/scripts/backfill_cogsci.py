"""Source-bounded official CogSci metadata enumeration; no full text downloaded."""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.collectors.cogsci_oai import parse_page
from app.collectors.crossref import request_with_retry
from app.db import _make_engine
from app.models import Venue
from scripts.backfill_usenix import apply_records
from scripts.reconcile_papers import _backup


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "venue": "CogSci",
        "source": "https://escholarship.org/oai",
        "set": "cognitivesciencesociety",
        "pdf_downloads": 0,
        "full_coverage_verified": False,
        "status": "running",
        "pages": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    token = None
    seen = set()
    totals = Counter()

    def save():
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            for page in range(100):
                params = (
                    {"verb": "ListRecords", "resumptionToken": token}
                    if token
                    else {
                        "verb": "ListRecords",
                        "metadataPrefix": "oai_dc",
                        "set": "cognitivesciencesociety",
                        "from": "2023-01-01T00:00:00Z",
                    }
                )
                r = await request_with_retry(
                    client, report["source"], params=params, attempts=4
                )
                r.raise_for_status()
                if len(r.content) > 10_000_000:
                    raise ValueError("Oversized metadata page")
                (args.output / f"page-{page}.xml").write_text(r.text, encoding="utf-8")
                records, next_token, count = parse_page(r.text)
                if args.apply and records:
                    with Session(engine) as db:
                        venue = db.query(Venue).filter_by(abbr="CogSci").one()
                        totals.update(apply_records(db, venue, records))
                report["pages"].append(
                    {
                        "page": page,
                        "metadata_records": count,
                        "accepted_records": len(records),
                    }
                )
                report["counts"] = dict(totals)
                save()
                print(json.dumps(report["pages"][-1]), flush=True)
                if not next_token:
                    report["status"] = "source_metadata_enumerated"
                    save()
                    return report
                if next_token in seen:
                    raise ValueError("Repeated OAI resumption token")
                seen.add(next_token)
                token = next_token
                await asyncio.sleep(0.6)
        raise ValueError("OAI safety page bound reached")
    finally:
        engine.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
