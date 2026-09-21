"""Create a new SQLite snapshot without deleting older backups or touching archives."""
import sqlite3
from datetime import datetime, timezone

from app.db import db_file_path


def main():
    source = db_file_path()
    if source is None or not source.is_file():
        raise SystemExit("No existing SQLite database to back up")
    directory = source.parent / "backups"
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"lithub-{stamp}.db"
    with sqlite3.connect(source) as connection, sqlite3.connect(target) as backup:
        connection.backup(backup)
        if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup quick_check failed")
    print(target.resolve())


if __name__ == "__main__":
    main()
