"""Back up and reindex existing topics; never fetch papers, publish, or replace paper metadata."""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import _make_engine, db_file_path
from app.services.topic_index import reindex_topics


def paper_fingerprint(connection):
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute("SELECT * FROM papers ORDER BY id"):
        digest.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        count += 1
    manual = connection.execute("SELECT paper_id,direction_id,score,source,created_at FROM paper_directions WHERE source='manual' ORDER BY paper_id,direction_id").fetchall()
    return {"paper_count": count, "paper_sha256": digest.hexdigest(), "manual_tags": manual}


def reindex_database(path: Path, seeds_dir: Path):
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise ValueError("Expected an existing regular SQLite database")
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = backup_dir / f"before-topic-reindex-{stamp}.db"
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(backup) as target:
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Source database failed quick_check")
        before = paper_fingerprint(source)
        source.backup(target)
        if target.execute("PRAGMA quick_check").fetchone()[0] != "ok" or paper_fingerprint(target) != before:
            raise ValueError("Database backup verification failed")
    engine = _make_engine("sqlite:///" + path.as_posix())
    try:
        with sessionmaker(bind=engine, expire_on_commit=False)() as session:
            result = reindex_topics(session, seeds_dir)
            connection = session.connection().connection.driver_connection
            if paper_fingerprint(connection) != before:
                session.rollback()
                raise ValueError("Reindex attempted to change papers or manual tags")
            session.connection().exec_driver_sql("INSERT INTO papers_fts(papers_fts, rank) VALUES('integrity-check', 1)")
            session.commit()
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
            if source.execute("PRAGMA quick_check").fetchone()[0] != "ok" or paper_fingerprint(source) != before:
                raise ValueError("Post-reindex verification failed; backup retained")
    finally:
        engine.dispose()
    return {**result, "backup": str(backup), "paper_count_unchanged": before["paper_count"],
            "paper_metadata_unchanged": True, "manual_tags_unchanged": True, "fts_integrity": "ok"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=db_file_path())
    parser.add_argument("--seeds", type=Path, default=settings.seeds_dir)
    args = parser.parse_args()
    if args.database is None:
        parser.error("An existing SQLite database is required")
    print(json.dumps(reindex_database(args.database, args.seeds), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
