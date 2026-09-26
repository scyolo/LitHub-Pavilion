"""Allowlisted reader metadata, content-addressed chunks, and atomic manifest updates."""
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.api.filtering import PaperFilters, paper_query, venue_scope
from app.api.serializers import abstract_text, paper_card, safe_http_url
from app.models import Author, CrawlLog, Direction, Paper, PaperAuthor, PaperDirection, Venue
from app.services.snapshot_overview import OverviewBuilder

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 800 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}")
_CONTENT_PATH = re.compile(r"(catalog|papers)-([0-9a-f]{64})\.json")
_MANIFEST_KEYS = {"schema_version", "revision", "generated_at", "paper_count", "catalog", "chunks"}
_PAPER_KEYS = {
    "id", "title", "venue", "venue_name", "venue_type", "level", "year", "abstract_preview",
    "authors_preview", "publication_date", "created_at", "venue_confirmed", "directions",
    "first_author", "authors_count", "citation_count", "pdf_status", "pdf_source", "doi",
    "official_url", "oa_url", "abstract", "authors", "direction_details", "arxiv_id", "dblp_key", "updated_at",
}
_LOG_KEYS = {"run_id", "task_type", "status", "papers_new", "papers_updated", "started_at", "finished_at"}
_VENUE_KEYS = {"id", "abbr", "name", "type", "level", "ccf_area", "active"}


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def manifest_revision(manifest: dict) -> str:
    content = {key: manifest[key] for key in ("schema_version", "paper_count", "catalog", "chunks")}
    return hashlib.sha256(_json_bytes(content)).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise ValueError("Snapshot destination must not be a symlink")
    descriptor, temporary = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Exported metadata is read by the separate, unprivileged web container.
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_content(directory: Path, prefix: str, content: bytes) -> dict:
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("Snapshot chunk exceeds the file size limit")
    digest = hashlib.sha256(content).hexdigest()
    filename = f"{prefix}-{digest}.json"
    path = directory / filename
    if path.is_symlink():
        raise ValueError("Snapshot content must not be a symlink")
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError("Existing content-addressed snapshot file is corrupt")
        os.chmod(path, 0o644)
    else:
        _atomic_write(path, content)
    return {"path": filename, "sha256": digest}


def _public_logs(db):
    rows = (
        db.query(CrawlLog).filter(CrawlLog.venue_id.is_(None), CrawlLog.finished_at.isnot(None))
        .order_by(CrawlLog.started_at.desc(), CrawlLog.id.desc()).limit(100).all()
    )
    logs = []
    last_crawl = None
    for row in rows:
        failed_units = db.query(CrawlLog).filter(
            CrawlLog.run_id == row.run_id, CrawlLog.venue_id.isnot(None),
            CrawlLog.status.in_(("failed", "partial")),
        ).count()
        status = "partial" if row.status == "success" and failed_units else row.status
        item = {key: getattr(row, key) for key in _LOG_KEYS}
        item["status"] = status
        logs.append(item)
        if last_crawl is None and row.task_type in ("weekly", "backfill"):
            last_crawl = {key: value for key, value in item.items() if key != "task_type"}
            last_crawl["failed_units"] = failed_units
    return logs, last_crawl


def _catalog(db):
    logs, last_crawl = _public_logs(db)
    return {
        "venues": [
            {"id": venue.id, "abbr": venue.abbr, "name": venue.name, "type": venue.type,
             "level": venue.ccf_level, "ccf_area": venue.ccf_area, "active": venue.active}
            for venue in db.query(Venue).filter(*venue_scope(PaperFilters()))
            .order_by(Venue.type, Venue.ccf_level, Venue.abbr).all()
        ],
        "directions": [
            {"code": direction.code, "name": direction.name, "enabled": direction.enabled}
            for direction in db.query(Direction).order_by(Direction.code).all()
        ],
        "logs": logs,
        "last_crawl": last_crawl,
    }


def _paper_rows(db, papers):
    ids = [paper.id for paper in papers]
    authors = {}
    for pid, name, order in (
        db.query(PaperAuthor.paper_id, Author.name, PaperAuthor.author_order)
        .join(Author, PaperAuthor.author_id == Author.id).filter(PaperAuthor.paper_id.in_(ids))
        .order_by(PaperAuthor.paper_id, PaperAuthor.author_order, Author.id).all()
    ):
        authors.setdefault(pid, []).append({"name": name, "order": order})
    directions = {}
    details = {}
    for pid, code, name, score, source in (
        db.query(PaperDirection.paper_id, Direction.code, Direction.name, PaperDirection.score, PaperDirection.source)
        .join(Direction, PaperDirection.direction_id == Direction.id).filter(PaperDirection.paper_id.in_(ids))
        .order_by(PaperDirection.paper_id, Direction.code).all()
    ):
        directions.setdefault(pid, []).append(code)
        details.setdefault(pid, []).append({"code": code, "name": name, "score": score, "source": source})
    summaries = {
        pid: {"first_author": next((author["name"] for author in values if author["order"] == 1), None),
              "authors_count": len(values), "authors_preview": [author["name"] for author in values[:3]]}
        for pid, values in authors.items()
    }
    return [
        {**paper_card(paper, directions, summaries), "abstract": abstract_text(paper.abstract),
         "authors": authors.get(paper.id, []), "direction_details": details.get(paper.id, []),
         "arxiv_id": paper.arxiv_id, "dblp_key": paper.dblp_key, "updated_at": paper.updated_at}
        for paper in papers
    ]


def export_snapshot(session_factory, directory: Path, *, chunk_size: int = 500,
                    generated_at: datetime | None = None, allow_empty: bool = False) -> dict:
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Snapshot directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    if not 1 <= chunk_size <= 1000:
        raise ValueError("chunk_size must be between 1 and 1000")
    previous = validate_snapshot(directory) if (directory / "manifest.json").exists() else None
    chunks = []
    total_bytes = 0
    with session_factory() as db:
        # pysqlite otherwise does not start a read transaction for SELECT statements.
        if db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN")
        query = paper_query(db, PaperFilters())
        count = query.count()
        if not count and (not allow_empty or (previous and previous["paper_count"] > 0)):
            raise ValueError("Refusing to replace the website with an empty snapshot")
        catalog_value = _catalog(db)
        last_id = 0
        while True:
            papers = query.filter(Paper.id > last_id).order_by(Paper.id).limit(chunk_size).all()
            if not papers:
                break
            rows = _paper_rows(db, papers)
            pending = [rows]
            while pending:
                group = pending.pop(0)
                content = _json_bytes(group)
                if len(content) > MAX_FILE_BYTES and len(group) > 1:
                    half = len(group) // 2
                    pending[0:0] = [group[:half], group[half:]]
                    continue
                total_bytes += len(content)
                if total_bytes > MAX_SNAPSHOT_BYTES:
                    raise ValueError("Snapshot exceeds the total size limit")
                chunks.append({**_write_content(directory, "papers", content), "count": len(group)})
            last_id = papers[-1].id
            db.expunge_all()
    timestamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    if previous and count == previous["paper_count"] and chunks == previous["chunks"]:
        old_catalog, _ = _load_entry(directory, previous["catalog"], "catalog")
        if {key: value for key, value in old_catalog.items() if key != "overview"} == catalog_value:
            timestamp = previous["generated_at"]
    overview = OverviewBuilder(catalog_value, timestamp)
    for entry in chunks:
        rows, _ = _load_entry(directory, entry, "papers")
        overview.add(rows)
    catalog_value["overview"] = overview.result()
    catalog_data = _json_bytes(catalog_value)
    if total_bytes + len(catalog_data) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot exceeds the total size limit")
    catalog = _write_content(directory, "catalog", catalog_data)
    manifest = {
        "schema_version": SCHEMA_VERSION, "paper_count": count,
        "catalog": catalog, "chunks": chunks,
        "generated_at": timestamp,
    }
    manifest["revision"] = manifest_revision(manifest)
    if previous and previous["revision"] == manifest["revision"]:
        os.chmod(directory / "manifest.json", 0o644)
        return previous
    _validate_contents(directory, manifest)
    if previous:
        _atomic_write(directory / "previous-manifest.json", _json_bytes(previous))
    _atomic_write(directory / "manifest.json", _json_bytes(manifest))
    return manifest


def _reject_constant(value):
    raise ValueError("Snapshot JSON contains a non-finite number")


def _read_json(path: Path, *, max_bytes: int = MAX_FILE_BYTES):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            raise ValueError("Snapshot file is missing, unsafe, or too large")
        content = path.read_bytes()
        return json.loads(content, parse_constant=_reject_constant), content
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Snapshot file cannot be read as JSON") from exc


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _check_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"Invalid public {label} fields")


def _load_entry(directory, entry, prefix):
    keys = {"path", "sha256", "count"} if prefix == "papers" else {"path", "sha256"}
    _check_keys(entry, keys, "file entry")
    path = entry["path"]
    match = _CONTENT_PATH.fullmatch(path) if isinstance(path, str) else None
    if not match or match[1] != prefix or match[2] != entry["sha256"]:
        raise ValueError("Invalid snapshot file path or digest")
    value, content = _read_json(directory / path)
    if hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise ValueError("Snapshot content hash does not match")
    return value, len(content)


def _validate_contents(directory: Path, manifest: dict) -> None:
    _check_keys(manifest, _MANIFEST_KEYS, "manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported snapshot schema version")
    if not _timestamp(manifest["generated_at"]) or not _integer(manifest["paper_count"]):
        raise ValueError("Invalid snapshot generation time or count")
    if not isinstance(manifest["revision"], str) or not _HASH.fullmatch(manifest["revision"]):
        raise ValueError("Invalid snapshot revision")
    if not isinstance(manifest["chunks"], list) or len(manifest["chunks"]) > 4096:
        raise ValueError("Invalid snapshot chunk list")
    if manifest_revision(manifest) != manifest["revision"]:
        raise ValueError("Snapshot revision does not match its contents")
    catalog, total_bytes = _load_entry(directory, manifest["catalog"], "catalog")
    _check_keys(catalog, {"venues", "directions", "logs", "last_crawl"} | ({"overview"} if "overview" in catalog else set()), "catalog")
    if not all(isinstance(catalog[name], list) for name in ("venues", "directions", "logs")):
        raise ValueError("Invalid snapshot catalog lists")
    venues = {}
    for venue in catalog["venues"]:
        _check_keys(venue, _VENUE_KEYS, "venue")
        if venue["level"] not in ("A", "B") or venue["type"] not in ("conf", "journal"):
            raise ValueError("Venue is outside the public scope")
        if not isinstance(venue["abbr"], str) or venue["abbr"] in venues:
            raise ValueError("Invalid or duplicate venue")
        venues[venue["abbr"]] = venue
    codes = set()
    for direction in catalog["directions"]:
        _check_keys(direction, {"code", "name", "enabled"}, "direction")
        if not isinstance(direction["code"], str) or direction["code"] in codes:
            raise ValueError("Invalid or duplicate direction")
        codes.add(direction["code"])
    if len(catalog["logs"]) > 100:
        raise ValueError("Too many public collection logs")
    for row in catalog["logs"]:
        _check_keys(row, _LOG_KEYS, "collection log")
    if catalog["last_crawl"] is not None:
        _check_keys(catalog["last_crawl"], (_LOG_KEYS - {"task_type"}) | {"failed_units"}, "last collection")
    ids = set()
    overview = OverviewBuilder(catalog, manifest["generated_at"]) if "overview" in catalog else None
    for entry in manifest["chunks"]:
        rows, length = _load_entry(directory, entry, "papers")
        total_bytes += length
        if total_bytes > MAX_SNAPSHOT_BYTES:
            raise ValueError("Snapshot exceeds the total size limit")
        if not isinstance(rows, list) or not _integer(entry["count"], 1) or len(rows) != entry["count"]:
            raise ValueError("Snapshot chunk count does not match")
        for row in rows:
            _check_keys(row, _PAPER_KEYS, "paper")
            pid = row["id"]
            if not _integer(pid, 1) or pid in ids:
                raise ValueError("Invalid or duplicate paper id")
            ids.add(pid)
            if row["level"] not in ("A", "B") or row["venue_type"] not in ("conf", "journal") or row["venue"] not in venues:
                raise ValueError("Paper is outside the public scope")
            if not isinstance(row["title"], str) or not row["title"].strip() or not _integer(row["year"]) or not 2000 <= row["year"] <= 2100:
                raise ValueError("Invalid paper title or year")
            for key in ("official_url", "oa_url"):
                if row[key] is not None and safe_http_url(row[key]) != row[key]:
                    raise ValueError("Unsafe public paper link")
            if not isinstance(row["authors"], list) or not isinstance(row["directions"], list) or not isinstance(row["direction_details"], list):
                raise ValueError("Invalid paper authors or directions")
            for author in row["authors"]:
                _check_keys(author, {"name", "order"}, "author")
                if not isinstance(author["name"], str) or not _integer(author["order"], 1):
                    raise ValueError("Invalid author")
            for detail in row["direction_details"]:
                _check_keys(detail, {"code", "name", "score", "source"}, "paper direction")
                if detail["code"] not in codes or not isinstance(detail["score"], (int, float)) or not math.isfinite(detail["score"]):
                    raise ValueError("Invalid paper direction")
            if sorted(row["directions"]) != sorted(detail["code"] for detail in row["direction_details"]):
                raise ValueError("Paper direction details do not match")
        if overview is not None:
            overview.add(rows)
    if overview is not None and _json_bytes(catalog["overview"]) != _json_bytes(overview.result()):
        raise ValueError("Public overview does not match the complete snapshot")
    if len(ids) != manifest["paper_count"]:
        raise ValueError("Snapshot paper count does not match")


def validate_snapshot(directory: Path) -> dict:
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Snapshot directory must not be a symlink")
    manifest, _ = _read_json(directory / "manifest.json", max_bytes=1024 * 1024)
    try:
        _validate_contents(directory, manifest)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid snapshot structure") from exc
    return manifest
