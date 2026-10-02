"""Revision-bound compressed indexes and on-demand original paper details."""
import gzip
import hashlib
import io
import json
import re
from pathlib import Path

FIELDS = [
    "id", "title", "venue", "year", "publication_date", "created_at",
    "citation_count", "directions", "venue_confirmed", "doi", "official_url",
    "oa_url", "first_author", "authors_count", "pdf_status", "pdf_source",
]


def load_reader_descriptor(directory, catalog):
    reader = catalog.get("reader", {})
    if reader.get("version") not in (4, 6):
        return reader
    _, raw = read_compressed_asset(directory, reader["index"])
    return decode_reader_descriptor(raw, reader)


def decode_reader_descriptor(raw, reader):
    descriptor = json.loads(raw)
    if (set(reader) != {"version", "paper_count", "index"} or reader["index"].get("count") != reader["paper_count"]
            or not isinstance(descriptor, dict) or descriptor.get("version") != (5 if reader.get("version") == 6 else 3)
            or descriptor.get("paper_count") != reader["paper_count"]):
        raise ValueError("Detached reader descriptor mismatch")
    return descriptor


def reader_entries(catalog, directory=None, *, descriptor=None):
    reader = catalog.get("reader", {})
    detached = []
    if reader.get("version") in (4, 6):
        detached = [reader["index"]]
        if descriptor is None:
            if directory is None:
                raise ValueError("Detached reader requires its verified descriptor")
            descriptor = load_reader_descriptor(directory, catalog)
        reader = descriptor
    entries = [*detached, *reader.get("browse", []), *reader.get("details", [])]
    for section in ("terms", "titles"):
        for parts in reader.get("search", {}).get(section, {}).values():
            entries.extend(parts)
    entries.extend(reader.get('search', {}).get('vocabulary', []))
    entries.extend(reader.get('ranking', {}).get('parts', []))
    for entry in entries:
        if not re.fullmatch(r"(?:reader|browse|compressed|search|titles|vocabulary|ranking)-[0-9a-f]{64}\.json\.gz", entry["path"]) or entry["sha256"] not in entry["path"]:
            raise ValueError("Unsafe reader asset path")
    return entries


def read_compressed_asset(directory, entry):
    from app.services.snapshot import MAX_FILE_BYTES

    reader_entries({"reader": {"browse": [entry]}})
    path = Path(directory) / entry["path"]
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Unsafe reader asset")
    content = path.read_bytes()
    return content, decode_compressed_asset(content, entry)


def decode_compressed_asset(content, entry):
    from app.services.snapshot import MAX_FILE_BYTES
    reader_entries({"reader": {"browse": [entry]}})
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("Reader asset exceeds size limit")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
    except (OSError, EOFError) as exc:
        raise ValueError("Invalid compressed reader asset") from exc
    if len(raw) > MAX_FILE_BYTES or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("Reader asset size or digest mismatch")
    return raw


def build_reader_assets(directory: Path, manifest: dict, *, write=True, version=3) -> dict:
    from app.services.snapshot import MAX_FILE_BYTES, _atomic_write, _json_bytes, _load_entry

    directory = Path(directory)
    index = {"version": version,
             "paper_count": manifest["paper_count"], "fields": FIELDS, "browse": [], "details": []}
    pending = []

    def emit(prefix, content, count):
        if len(content) > MAX_FILE_BYTES:
            raise ValueError("Reader asset exceeds the size limit")
        digest = hashlib.sha256(content).hexdigest()
        entry = {"path": f"{prefix}-{digest}.json.gz", "sha256": digest, "count": count}
        path = directory / entry["path"]
        if path.exists() or path.is_symlink() or not write:
            _, existing = read_compressed_asset(directory, entry)
            if existing != content:
                raise ValueError("Reader asset does not match source records")
        else:
            compressed = gzip.compress(content, mtime=0)
            if len(compressed) > MAX_FILE_BYTES:
                raise ValueError("Compressed reader asset exceeds the size limit")
            _atomic_write(path, compressed)
        return entry

    def write_browse(rows):
        content = _json_bytes(rows)
        if len(content) > MAX_FILE_BYTES and len(rows) > 1:
            middle = len(rows) // 2
            write_browse(rows[:middle])
            write_browse(rows[middle:])
            return
        if len(content) > MAX_FILE_BYTES:
            raise ValueError("Browse record exceeds the reader size limit")
        entry = emit("browse", content, len(rows))
        if version >= 2:
            entry.update(min_id=min(row[0] for row in rows), max_id=max(row[0] for row in rows))
        index["browse"].append(entry)

    for entry in manifest["chunks"]:
        rows, _ = _load_entry(directory, entry, "papers")
        content = (directory / entry["path"]).read_bytes()
        compressed = emit("compressed", content, len(rows))
        index["details"].append({
            **compressed,
            "min_id": min(row["id"] for row in rows), "max_id": max(row["id"] for row in rows),
            "venues": sorted({row["venue"] for row in rows}),
            "years": sorted({row["year"] for row in rows}),
            "directions": sorted({code for row in rows for code in row["directions"]}),
        })
        pending.extend([[row[field] for field in FIELDS] for row in rows])
        if version >= 5:
            while len(pending) >= 256:
                write_browse(pending[:256])
                pending = pending[256:]
        elif len(pending) >= 4000:
            write_browse(pending)
            pending = []
    if pending:
        write_browse(pending)
    if version >= 2:
        from app.services.snapshot_search import build_search_assets
        index["search"] = build_search_assets(directory, manifest, emit, version=3 if version >= 5 else 2 if version >= 3 else 1)
    if version >= 5:
        from app.services.snapshot_ranking import build_ranking_assets
        index["ranking"] = build_ranking_assets(directory, manifest, emit)
    if version in (4, 6):
        index["version"] = 5 if version == 6 else 3
        entry = emit("reader", _json_bytes(index), manifest["paper_count"])
        return {"version": version, "paper_count": manifest["paper_count"], "index": entry}
    return index


def ensure_snapshot_reader(directory: Path, manifest: dict) -> dict:
    from app.services.snapshot import _json_bytes, _load_entry, _write_content, manifest_revision

    catalog, _ = _load_entry(directory, manifest["catalog"], "catalog")
    catalog["reader"] = build_reader_assets(directory, manifest, version=6)
    upgraded = {**manifest, "catalog": _write_content(directory, "catalog", _json_bytes(catalog))}
    upgraded["revision"] = manifest_revision(upgraded)
    return upgraded
