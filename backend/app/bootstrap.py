"""Idempotent SQLite initialization; existing settings and paper records are never replaced."""
import csv
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Base, Direction, DirectionRule, FTS_DDL, PdfWhitelist, Venue


def _rows(directory: Path, filename: str):
    with (directory / filename).open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def seed_missing(session: Session, directory: Path) -> None:
    for row in _rows(directory, "venues.csv"):
        if session.query(Venue.id).filter(Venue.abbr == row["abbr"]).first():
            continue
        if row["ccf_level"] not in ("A", "B") or row["type"] not in ("conf", "journal"):
            raise ValueError("Seed contains a venue outside the configured A/B scope")
        session.add(Venue(
            abbr=row["abbr"], name=row["name"], dblp_stream=row["dblp_stream"],
            dblp_toc_pattern=row.get("dblp_toc_pattern") or None,
            issn=row.get("issn") or None, openalex_source_id=row.get("openalex_source_id") or None,
            s2_venue=row.get("s2_venue") or None, type=row["type"], ccf_level=row["ccf_level"],
            ccf_area=row.get("ccf_area") or "人工智能", active=int(row.get("active", "1")),
        ))
    for row in _rows(directory, "directions.csv"):
        if not session.query(Direction.id).filter(Direction.code == row["code"]).first():
            session.add(Direction(code=row["code"], name=row["name"], min_score=float(row["min_score"]), enabled=int(row["enabled"])))
    session.flush()
    directions = {direction.code: direction.id for direction in session.query(Direction).all()}
    for row in _rows(directory, "direction_rules.csv"):
        re.compile(row["keyword"])
        direction_id = directions[row["direction_code"]]
        exists = session.query(DirectionRule.id).filter(DirectionRule.direction_id == direction_id, DirectionRule.keyword == row["keyword"]).first()
        if not exists:
            session.add(DirectionRule(direction_id=direction_id, keyword=row["keyword"], field=row["field"], weight=float(row["weight"]), enabled=int(row["enabled"])))
    for row in _rows(directory, "pdf_whitelist.csv"):
        if session.get(PdfWhitelist, row["host"]) is None:
            session.add(PdfWhitelist(host=row["host"], owner=row["owner"], note=row["note"], enabled=1))
    session.commit()


def _backup(engine) -> None:
    database = make_url(str(engine.url)).database
    if not database or database == ":memory:" or not Path(database).is_file():
        return
    directory = Path(database).parent / "backups"
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    with sqlite3.connect(database) as source, sqlite3.connect(directory / f"before-schema-update-{stamp}.db") as target:
        source.backup(target)


def initialize_database(engine, seeds_dir: Path | None = None) -> None:
    if engine.dialect.name != "sqlite":
        raise RuntimeError("This release requires SQLite with FTS5; PostgreSQL needs a search adapter")
    existing = inspect(engine)
    new_database = not existing.has_table("venues")
    if existing.has_table("venues") and "s2_venue" not in {column["name"] for column in existing.get_columns("venues")}:
        _backup(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE venues ADD COLUMN s2_venue TEXT")
    Base.metadata.create_all(engine)
    current = inspect(engine)
    for table in Base.metadata.sorted_tables:
        present = {column["name"] for column in current.get_columns(table.name)}
        missing = set(table.columns.keys()) - present
        if missing:
            raise RuntimeError(f"Unsupported legacy schema in {table.name}: {', '.join(sorted(missing))}; back up and migrate before startup")
    with engine.begin() as connection:
        fts_exists = connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name='papers_fts'").first() is not None
        for statement in FTS_DDL:
            connection.exec_driver_sql(statement)
        if not fts_exists:
            connection.exec_driver_sql("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")
    if new_database:
        with Session(engine) as session:
            seed_missing(session, Path(seeds_dir or settings.seeds_dir))
