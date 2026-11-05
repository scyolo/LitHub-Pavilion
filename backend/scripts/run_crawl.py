"""Run one collection round through the production pipeline.

Thin driver over the same methods CrawlPipeline._run uses, so upstream pause
semantics (OpenAlex/S2 budget, Crossref 429 backoff) behave exactly as in the app.

Usage: python -m scripts.run_crawl --years 2026 [--abbrs A,B] [--limit N] [--out FILE]
"""
import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.db import _make_engine, db_file_path
from app.models import CrawlLog, CrawlState, Venue, utcnow_iso
from app.services.pipeline import BATCH_SIZE, CrawlPipeline


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[2026])
    ap.add_argument("--abbrs", default="", help="comma separated venue abbreviations")
    ap.add_argument("--limit", type=int, default=0, help="max venues (0 = all)")
    ap.add_argument("--skip-complete", action="store_true", help="skip checkpointed units")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    engine = _make_engine("sqlite:///" + db_file_path().as_posix())
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()

    query = session.query(Venue).filter(
        Venue.active == 1, Venue.ccf_level.in_(("A", "B")))
    if args.abbrs:
        wanted = [a.strip() for a in args.abbrs.split(",") if a.strip()]
        query = query.filter(Venue.abbr.in_(wanted))
    venues = query.order_by(Venue.abbr).all()
    if args.limit:
        venues = venues[: args.limit]

    years = sorted(set(args.years))
    pipeline = CrawlPipeline(Session)          # one instance = production pause semantics
    run = CrawlLog(run_id="manual-" + utcnow_iso().replace(":", "").replace("-", "")[:15],
                   task_type="backfill", status="running", started_at=utcnow_iso())
    session.add(run)
    session.commit()

    results = []
    total_new = 0
    total_updated = 0

    for venue in venues:
        for year in years:
            key = f"backfill:{venue.dblp_stream or 'venue-' + str(venue.id)}:{year}"
            if args.skip_complete and session.query(CrawlState).filter(
                    CrawlState.scope_key == key, CrawlState.cursor == "complete-v6").first():
                continue
            session.rollback()
            unit = CrawlLog(run_id=run.run_id, task_type="backfill", venue_id=venue.id,
                            year=year, status="running", started_at=utcnow_iso())
            session.add(unit)
            session.commit()
            try:
                pipeline._collection_issue = None
                pipeline._ingest_conflicts = False
                raws, incomplete = await pipeline._collect_unit_async(session, venue, year, False)
                created = updated = 0
                if raws:
                    for start in range(0, len(raws), BATCH_SIZE):
                        batch = raws[start:start + BATCH_SIZE]
                        ids, new, upd = await pipeline._db_call(
                            pipeline._ingest_owned, batch, venue.id, year)
                        created += new
                        updated += upd
                        await pipeline._db_call(pipeline._tag_owned, ids)
                incomplete = incomplete or pipeline._ingest_conflicts
                status = "partial" if incomplete or not raws else "ok"
                unit.status = "partial" if status == "partial" else "success"
                unit.papers_new = created
                unit.papers_updated = updated
                unit.error = (pipeline._collection_issue or "")[:500] or None
                unit.finished_at = utcnow_iso()
                session.commit()
                if status == "ok":
                    state = session.query(CrawlState).filter(CrawlState.scope_key == key).one_or_none()
                    if state is None:
                        session.add(CrawlState(scope_key=key, cursor="complete-v6"))
                    else:
                        state.cursor = "complete-v6"
                    session.commit()
                total_new += created
                total_updated += updated
                results.append({"venue": venue.abbr, "year": year, "status": status,
                                "raws": len(raws), "new": created, "updated": updated,
                                "issue": (pipeline._collection_issue or "")[:200]})
                print(f"{venue.abbr:30s} {year} {status:8s} raws={len(raws):5d} "
                      f"new={created:5d} upd={updated:5d} {(pipeline._collection_issue or '')[:50]}",
                      flush=True)
            except Exception as exc:
                session.rollback()
                unit = session.merge(unit)
                unit.status = "failed"
                unit.error = f"{type(exc).__name__}: {str(exc)[:200]}"
                unit.finished_at = utcnow_iso()
                session.commit()
                results.append({"venue": venue.abbr, "year": year, "status": "failed",
                                "raws": 0, "new": 0, "updated": 0,
                                "issue": f"{type(exc).__name__}: {str(exc)[:150]}"})
                print(f"{venue.abbr:30s} {year} FAILED   {type(exc).__name__}: {str(exc)[:60]}",
                      flush=True)

    summary = {
        "venues": len(venues), "years": years, "units": len(results),
        "papers_new": total_new, "papers_updated": total_updated,
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "partial": sum(1 for r in results if r["status"] == "partial"),
        "empty": sum(1 for r in results if r["status"] == "empty"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
    }
    successes, partials, failures = summary["ok"], summary["partial"], summary["failed"]
    run.status = ("failed" if failures and not successes and not partials else
                  "partial" if failures or partials else "success")
    run.error = f"complete={successes}; partial={partials}; failed={failures}"
    run.papers_new = total_new
    run.papers_updated = total_updated
    run.finished_at = utcnow_iso()
    session.commit()
    session.close()
    engine.dispose()

    print("\nSUMMARY " + json.dumps(summary, ensure_ascii=False))
    if args.out:
        Path(args.out).write_text(
            json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
