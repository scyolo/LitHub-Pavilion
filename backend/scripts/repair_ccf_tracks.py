"""Revoke unsupported CCF main-track confirmations; preserve records and user data."""
import argparse
import json
from pathlib import Path
from sqlalchemy.orm import Session
from app.collectors.dblp import RawPaper
from app.db import _make_engine, db_file_path
from app.models import Paper
from app.services.paper_store import ccf_track_eligible
from scripts.reconcile_papers import _backup


def repair_tracks(path, *, apply=False):
    path = Path(path).resolve()
    result = {"dry_run": not apply, "changes": []}
    if apply:
        result["backup"] = str(_backup(path))
    engine = _make_engine("sqlite:///" + path.as_posix())
    try:
        with Session(engine) as session:
            for p in session.query(Paper).filter(Paper.venue_confirmed == 1):
                raw = RawPaper(source=p.source, venue_key=p.dblp_key or p.publisher_key or p.official_url,
                    title=p.title, authors=[], year=p.year, doi=p.doi, official_url=p.official_url,
                    extra={"publisher_key": p.publisher_key})
                if ccf_track_eligible(raw, p.venue):
                    continue
                result["changes"].append({"id": p.id, "doi": p.doi, "venue": p.venue.abbr})
                if apply:
                    p.venue_confirmed = 0
                    note = "CCF scope: official non-main track; retained for search, not confirmed as main proceedings"
                    if note not in (p.note or ""):
                        p.note = ((p.note + "\n") if p.note else "") + note
            if apply:
                session.commit()
    finally:
        engine.dispose()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=db_file_path())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = repair_tracks(args.database, apply=args.apply)
    print(json.dumps({**result, "changes": len(result["changes"])}))


if __name__ == "__main__":
    main()
