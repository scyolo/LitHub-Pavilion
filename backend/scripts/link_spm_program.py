"""Associate the verified SPM 2023 official program with canonical CAD publications."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.collectors.crossref import request_with_retry
from app.collectors.spm_program import parse_spm_program
from app.db import _make_engine
from app.models import Venue
from app.services.paper_conferences import associate_title_listing
from scripts.reconcile_papers import _backup

SOURCE = "https://sites.google.com/view/spm-2023/program"


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "program-2023.html"
    if path.exists():
        html = path.read_text(encoding="utf-8")
    else:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await request_with_retry(client, SOURCE)
            response.raise_for_status()
            if len(response.content) > 3_000_000 or "html" not in response.headers.get(
                "content-type", ""
            ):
                raise ValueError("Unexpected SPM program response")
            html = response.text
            path.write_text(html, encoding="utf-8")
    rows = parse_spm_program(html, 2023)
    digest = hashlib.sha256(html.encode()).hexdigest()
    report = {
        "venue": "SPM",
        "year": 2023,
        "source": SOURCE,
        "sha256": digest,
        "complete": False,
        "applied": args.apply,
        "pdf_downloads": 0,
        "papers": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        with Session(engine) as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            conf = db.query(Venue).filter_by(abbr="SPM").one()
            journal = db.query(Venue).filter_by(abbr="CAD").one()
            for raw in rows:
                item = {"title": raw.title, "authors": raw.authors}
                try:
                    with db.begin_nested():
                        link, new = associate_title_listing(
                            db,
                            conf,
                            raw,
                            journal.id,
                            SOURCE,
                            digest,
                            allow_initial_only=True,
                        )
                        item.update(status="linked", paper_id=link.paper_id, new=new)
                except ValueError as error:
                    item.update(status="unresolved", error=str(error))
                report["papers"].append(item)
            if args.apply:
                db.commit()
            else:
                db.rollback()
    finally:
        engine.dispose()
    report["matched_publications"] = sum(
        p["status"] == "linked" for p in report["papers"]
    )
    report["listed_long_papers"] = len(rows)
    target = args.output / "report.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)
    print(
        json.dumps(
            {
                k: report[k]
                for k in [
                    "venue",
                    "year",
                    "applied",
                    "matched_publications",
                    "listed_long_papers",
                    "complete",
                ]
            }
        )
    )
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
