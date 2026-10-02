"""Link official Performance programs to existing journal papers; no PDF requests or duplicate papers."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.collectors.crossref import request_with_retry
from app.collectors.performance_program import parse_program
from app.db import _make_engine
from app.models import Venue
from app.services.paper_conferences import associate_title_listing
from scripts.reconcile_papers import _backup

PROGRAMS = {
    2023: "https://performance2023.sciencesconf.org/resource/page/id/6",
    2025: "https://performance2025.sciencesconf.org/resource/page/id/3",
}


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "venue": "Performance",
        "pdf_downloads": 0,
        "complete": False,
        "applied": args.apply,
        "units": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))

    def save():
        path = args.output / "report.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(path)

    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            for year, url in PROGRAMS.items():
                cache = args.output / f"program-{year}.html"
                if cache.exists():
                    html = cache.read_text(encoding="utf-8")
                else:
                    response = await request_with_retry(client, url)
                    response.raise_for_status()
                    if len(
                        response.content
                    ) > 3_000_000 or "html" not in response.headers.get(
                        "content-type", ""
                    ):
                        raise ValueError("Unexpected program response")
                    html = response.text
                    cache.write_text(html, encoding="utf-8")
                rows, scope = parse_program(html, year)
                digest = hashlib.sha256(html.encode()).hexdigest()
                unit = {
                    "year": year,
                    "source": url,
                    "sha256": digest,
                    "scope": scope,
                    "papers": [],
                    "complete": False,
                }
                report["units"].append(unit)
                save()
                with Session(engine) as db:
                    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                    conf = db.query(Venue).filter_by(abbr="Performance").one()
                    journal = (
                        db.query(Venue)
                        .filter_by(
                            abbr="Performance Evaluation: An International Journal"
                        )
                        .one()
                    )
                    for row in rows:
                        item = {"title": row.title, "authors": row.authors}
                        try:
                            with db.begin_nested():
                                link, new = associate_title_listing(
                                    db,
                                    conf,
                                    row,
                                    journal.id,
                                    url,
                                    digest,
                                    allow_initial_only=year == 2025,
                                )
                                item.update(
                                    status="linked", paper_id=link.paper_id, new=new
                                )
                        except ValueError as error:
                            item.update(status="unresolved", error=str(error))
                        unit["papers"].append(item)
                    if args.apply:
                        db.commit()
                    else:
                        db.rollback()
                unit["matched_publications"] = sum(
                    p["status"] == "linked" for p in unit["papers"]
                )
                save()
                print(
                    json.dumps(
                        {
                            "year": year,
                            "matched": unit["matched_publications"],
                            "listed": len(rows),
                            "complete": False,
                        }
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
    p.add_argument("--apply", action="store_true")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
