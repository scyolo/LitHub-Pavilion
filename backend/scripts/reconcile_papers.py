"""Reconcile safe cross-source title/venue/year duplicates without changing manual labels."""
import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.cleaning import normalize_arxiv_id
from app.db import _make_engine, db_file_path
from app.models import Author, Paper, PaperAuthor, PaperDirection
from app.services.paper_store import is_repository_doi


def _backup(path: Path) -> Path:
    directory = path.parent / "backups"
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"before-paper-reconcile-{stamp}.db"
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(target)) as backup:
        if source.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("source database failed quick_check")
        source.backup(backup)
        if backup.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("backup failed quick_check")
    return target


def _prefer(canonical: Paper, duplicate: Paper) -> None:
    for field in ("abstract", "oa_url", "dblp_mdate"):
        if not getattr(canonical, field) and getattr(duplicate, field):
            setattr(canonical, field, getattr(duplicate, field))
    if duplicate.note and duplicate.note not in (canonical.note or ""):
        canonical.note = ((canonical.note + "\n") if canonical.note else "") + duplicate.note
    if canonical.publication_date is None and duplicate.publication_date and duplicate.publication_date.startswith(f"{canonical.year:04d}-"):
        canonical.publication_date = duplicate.publication_date
    canonical.citation_count = max(canonical.citation_count or 0, duplicate.citation_count or 0)
    canonical.venue_confirmed = max(canonical.venue_confirmed or 0, duplicate.venue_confirmed or 0)
    if duplicate.official_url and (canonical.official_url or "").startswith("https://dblp.org/db/"):
        canonical.official_url = duplicate.official_url



def _planned_unique_ids(canonical: Paper, duplicate: Paper) -> dict[str, str]:
    fields = ("dblp_key", "openalex_id", "doi", "arxiv_id", "s2_id", "publisher_key")
    result = {
        field: value
        for field in fields
        if (value := getattr(duplicate, field)) and not getattr(canonical, field)
    }
    if not canonical.arxiv_id and "arxiv_id" not in result:
        for paper in (canonical, duplicate):
            aid = normalize_arxiv_id((paper.doi or "").removeprefix("10.48550/arxiv."))
            if aid:
                result["arxiv_id"] = aid
                break
    return result


def _merge_one(session: Session, canonical: Paper, duplicate: Paper, *, authors_from: Paper | None = None) -> None:
    author_rows = None
    if authors_from is not None:
        author_rows = [(row.author_id, row.author_order) for row in session.query(PaperAuthor)
                       .filter(PaperAuthor.paper_id == authors_from.id).order_by(PaperAuthor.author_order)]
    _prefer(canonical, duplicate)
    preferred_doi = canonical.doi
    if duplicate.doi and (
        not preferred_doi or is_repository_doi(preferred_doi)
    ) and not is_repository_doi(duplicate.doi):
        preferred_doi = duplicate.doi
    pending_unique_ids = _planned_unique_ids(canonical, duplicate)
    aid = pending_unique_ids.get("arxiv_id") or canonical.arxiv_id
    if aid:
        if not canonical.oa_url:
            canonical.oa_url = "https://arxiv.org/abs/" + aid
        owner = session.query(Paper.id).filter(Paper.arxiv_id == aid,
                                              Paper.id.notin_((canonical.id, duplicate.id))).first()
        if owner:
            pending_unique_ids.pop("arxiv_id", None)

    if author_rows is not None:
        session.query(PaperAuthor).filter(PaperAuthor.paper_id.in_((canonical.id, duplicate.id))).delete(synchronize_session="fetch")
        session.flush()
        session.add_all(PaperAuthor(paper_id=canonical.id, author_id=aid, author_order=order)
                        for aid, order in author_rows)
    else:
        for row in session.query(PaperAuthor).filter(PaperAuthor.paper_id == duplicate.id).all():
            exists = session.query(PaperAuthor).filter(
                PaperAuthor.paper_id == canonical.id,
                PaperAuthor.author_id == row.author_id,
            ).one_or_none()
            if exists:
                session.delete(row)
            else:
                row.paper_id = canonical.id

    for row in session.query(PaperDirection).filter(PaperDirection.paper_id == duplicate.id).all():
        exists = session.query(PaperDirection).filter(
            PaperDirection.paper_id == canonical.id,
            PaperDirection.direction_id == row.direction_id,
        ).one_or_none()
        if exists:
            if row.source == "manual" and exists.source != "manual":
                exists.source = "manual"
                exists.score = row.score
            session.delete(row)
        else:
            row.paper_id = canonical.id

    # SQLite CHECK constraints are immediate. Do not temporarily null an
    # identity column on an openalex/dblp row; delete first, then move any
    # identities that only existed on the duplicate to the canonical row.
    session.delete(duplicate)
    session.flush()
    for field, value in pending_unique_ids.items():
        setattr(canonical, field, value)
    if preferred_doi:
        canonical.doi = preferred_doi
        canonical.official_url = "https://doi.org/" + preferred_doi
    if canonical.dblp_key:
        canonical.source = "dblp"
    elif canonical.openalex_id:
        canonical.source = "openalex"
    elif canonical.doi or canonical.arxiv_id or canonical.publisher_key:
        canonical.source = "manual"
    session.flush()


def reconcile(path: Path) -> dict:
    backup = _backup(path)
    engine = _make_engine("sqlite:///" + path.as_posix())
    groups = merged = skipped = 0
    try:
        with Session(engine) as session:
            duplicate_groups = (
                session.query(Paper.venue_id, Paper.year, Paper.title_norm)
                .filter(Paper.title_norm != "")
                .group_by(Paper.venue_id, Paper.year, Paper.title_norm)
                .having(func.count(Paper.id) > 1)
                .all()
            )
            for venue_id, year, title_norm in duplicate_groups:
                rows = (
                    session.query(Paper)
                    .filter(Paper.venue_id == venue_id, Paper.year == year, Paper.title_norm == title_norm)
                    .order_by(Paper.venue_confirmed.desc(), Paper.source.desc(), Paper.id)
                    .all()
                )
                # Same-title collisions are common in journal metadata and
                # DBLP abstract/reprint records. Only reconcile the clearly
                # attributable two-source case.
                if len(rows) != 2 or {row.source for row in rows} != {"dblp", "openalex"}:
                    skipped += 1
                    continue
                # A different publisher DOI needs manual/version review, not
                # a destructive title-only merge. Reprints are separate works.
                if all(row.doi and not is_repository_doi(row.doi) for row in rows) and rows[0].doi != rows[1].doi:
                    skipped += 1
                    continue
                if any(getattr(rows[0], field) and getattr(rows[1], field) and getattr(rows[0], field) != getattr(rows[1], field)
                       for field in ('arxiv_id', 'dblp_key', 'openalex_id', 's2_id', 'publisher_key')):
                    skipped += 1
                    continue
                authors = [{value for value, in session.query(Author.name_norm).join(PaperAuthor)
                            .filter(PaperAuthor.paper_id == row.id)} for row in rows]
                if not authors[0] or authors[0] != authors[1]:
                    skipped += 1
                    continue
                rows.sort(key=lambda row: (-int(bool(row.venue_confirmed)), -int(bool(row.dblp_key)), row.id))
                canonical, duplicate = rows
                _merge_one(session, canonical, duplicate)
                merged += 1
                groups += 1
            session.commit()
            quick = session.connection().exec_driver_sql("PRAGMA quick_check").scalar()
            count = session.query(func.count(Paper.id)).scalar()
            if quick != "ok":
                raise RuntimeError("post-reconcile quick_check failed")
    finally:
        engine.dispose()
    return {
        "backup": str(backup),
        "duplicate_groups": groups,
        "merged": merged,
        "skipped_ambiguous_groups": skipped,
        "paper_count": count,
        "quick_check": quick,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=db_file_path())
    args = parser.parse_args()
    if args.database is None or not args.database.is_file():
        parser.error("an existing SQLite database is required")
    print(json.dumps(reconcile(args.database.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
