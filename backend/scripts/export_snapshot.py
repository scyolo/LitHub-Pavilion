"""Export or validate reader snapshots without starting the API or fetching papers."""
import argparse
import asyncio
import json
from pathlib import Path

from app.config import settings
from app.db import _make_engine, db_file_path
from app.services.snapshot import export_snapshot, validate_snapshot
from sqlalchemy.orm import sessionmaker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=settings.snapshot_dir)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--allow-empty", action="store_true", help="Only for an explicit empty-site fixture; never replaces nonempty data")
    parser.add_argument("--publish", action="store_true", help="Upload the public snapshot and dispatch the Pages build")
    args = parser.parse_args()
    if args.validate_only:
        manifest = validate_snapshot(args.output)
    else:
        database = db_file_path()
        if database is None or not database.is_file():
            parser.error("Source database does not exist; refusing to create and publish an empty database")
        engine = _make_engine(settings.database_url)
        try:
            manifest = export_snapshot(sessionmaker(bind=engine, expire_on_commit=False), args.output, allow_empty=args.allow_empty)
        finally:
            engine.dispose()
    result = {"snapshot_status": "ready", "paper_count": manifest["paper_count"],
              "revision": manifest["revision"], "generated_at": manifest["generated_at"], "directory": str(args.output.resolve())}
    if args.publish:
        from app.services.snapshot_publish import publish_snapshot

        if not settings.pages_repository or not settings.pages_token_file.is_file():
            parser.error("Configure PAGES_REPOSITORY and PAGES_TOKEN_FILE before publishing")
        token = settings.pages_token_file.read_text(encoding="utf-8").strip()
        result["publication"] = asyncio.run(publish_snapshot(args.output, repository=settings.pages_repository, token=token))
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
