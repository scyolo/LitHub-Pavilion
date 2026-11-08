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
    if reader.get("version") not in (4, 6, 8, 10):
        return reader
    _, raw = read_compressed_asset(directory, reader["index"])
    return decode_reader_descriptor(raw, reader)


def decode_reader_descriptor(raw, reader):
    descriptor = json.loads(raw)
    if reader.get('version')==10:
        from app.services.snapshot_descriptor import unpack_descriptor
        descriptor=unpack_descriptor(descriptor)
    if (set(reader) != {"version", "paper_count", "index"} or reader["index"].get("count") != reader["paper_count"]
            or not isinstance(descriptor, dict) or descriptor.get("version") != reader["version"] - 1
            or descriptor.get("paper_count") != reader["paper_count"]):
        raise ValueError("Detached reader descriptor mismatch")
    return descriptor


def decode_author_descriptor(raw, pointer, paper_count):
    """Validate an author-only directory against its revision-bound pointer."""
    if (not isinstance(pointer, dict) or set(pointer) != {"version", "bucket_chars", "index"}
            or type(pointer["version"]) is not int or pointer["version"] != 1
            or type(pointer["bucket_chars"]) is not int or pointer["bucket_chars"] != 3):
        raise ValueError("Author directory pointer mismatch")
    index = pointer["index"]
    if (not isinstance(index, dict) or set(index) != {"path", "sha256", "count"}
            or type(index["count"]) is not int or index["count"] != paper_count
            or not isinstance(index["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", index["sha256"])
            or index["path"] != f"authors-{index['sha256']}.json.gz"):
        raise ValueError("Author directory asset mismatch")
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {"version", "bucket_chars", "terms"}
            or type(value["version"]) is not int or value["version"] != 1
            or type(value["bucket_chars"]) is not int or value["bucket_chars"] != 3
            or not isinstance(value["terms"], dict) or len(value["terms"]) > 4096):
        raise ValueError("Author directory fields mismatch")
    for key, parts in value["terms"].items():
        if not re.fullmatch(r"[0-9a-f]{3}", key) or not isinstance(parts, list) or not parts or len(parts) > 4096:
            raise ValueError("Author directory bucket mismatch")
        for part in parts:
            if (not isinstance(part, dict) or set(part) != {"path", "sha256", "count"}
                    or not isinstance(part["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])
                    or part["path"] != f"author-{part['sha256']}.json.gz"
                    or type(part["count"]) is not int or part["count"] < 1):
                raise ValueError("Author directory posting asset mismatch")
    return value


def reader_entries(catalog, directory=None, *, descriptor=None, author_descriptor=None, lookup_descriptors=None):
    reader = catalog.get("reader", {})
    detached = []
    if reader.get("version") in (4, 6, 8, 10):
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
    lookup = reader.get('search', {}).get('lookup')
    if lookup is not None:
        from app.services.snapshot_descriptor import decode_lookup_descriptor

        if (not isinstance(lookup, dict) or set(lookup) != {'version', 'bucket_chars', 'parts'}
                or type(lookup['version']) is not int or lookup['version'] != 1
                or type(lookup['bucket_chars']) is not int or lookup['bucket_chars'] != 1
                or not isinstance(lookup['parts'], dict) or len(lookup['parts']) > 16):
            raise ValueError('Invalid detached search lookup')
        if lookup_descriptors is not None and set(lookup_descriptors) != set(lookup['parts']):
            raise ValueError('Detached lookup descriptors do not match the reader')
        for prefix, entry in lookup['parts'].items():
            entries.append(entry)
            if lookup_descriptors is None:
                if directory is None:
                    raise ValueError('Detached search lookup requires its verified directory')
                _, raw = read_compressed_asset(directory, entry)
            else:
                raw = json.dumps(lookup_descriptors[prefix]).encode()
            content = decode_lookup_descriptor(raw, prefix, entry, reader['paper_count'])
            for section in ('terms', 'titles', 'metadata', 'hints'):
                for parts in content[section].values():
                    entries.extend(parts)
            for token in content.get('direct',{}).values():
                for parts in token.values():entries.extend(parts)
    for parts in reader.get('search', {}).get('metadata', {}).get('terms', {}).values():
        entries.extend(parts)
    for parts in reader.get('search', {}).get('hints', {}).get('terms', {}).values():
        entries.extend(parts)
    for token in reader.get('search',{}).get('direct',{}).values():
        for parts in token.values():entries.extend(parts)
    authors = reader.get('search', {}).get('authors')
    if authors is not None:
        if not isinstance(authors, dict) or 'index' not in authors:
            raise ValueError("Author directory requires a verified pointer")
        entries.append(authors['index'])
        if author_descriptor is None:
            if directory is None:
                raise ValueError("Author directory requires its verified descriptor")
            _, raw = read_compressed_asset(directory, authors['index'])
            author_descriptor = decode_author_descriptor(raw, authors, reader['paper_count'])
        else:
            author_descriptor = decode_author_descriptor(
                json.dumps(author_descriptor).encode(), authors, reader['paper_count'])
        for parts in author_descriptor['terms'].values():
            entries.extend(parts)
    entries.extend(reader.get('ranking', {}).get('parts', []))
    for entry in entries:
        if not re.fullmatch(r"(?:reader|browse|compressed|search|titles|vocabulary|ranking|author|authors|matchrank|cardhint|lookup)-[0-9a-f]{64}\.json\.gz", entry["path"]) or entry["sha256"] not in entry["path"]:
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


def build_reader_assets(directory: Path, manifest: dict, *, write=True, version=3, browse_chunk_size=128) -> dict:
    from app.services.snapshot import MAX_FILE_BYTES, _atomic_write, _json_bytes, _load_entry

    directory = Path(directory)
    if version not in range(1, 11):
        raise ValueError("Unsupported reader version")
    index = {"version": version,
             "paper_count": manifest["paper_count"], "fields": FIELDS, "browse": [], "details": []}
    # None reproduces historical v5/v6 bytes for full verification. New readers
    # carry an explicit packing size, without changing their search semantics.
    page_size = 256
    if version >= 5 and browse_chunk_size is not None:
        if type(browse_chunk_size) is not int or not 1 <= browse_chunk_size <= 4096:
            raise ValueError("Invalid browse chunk size")
        page_size = max(browse_chunk_size, (manifest["paper_count"] + 4095) // 4096)
        index["browse_chunk_size"] = page_size
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
            while len(pending) >= page_size:
                write_browse(pending[:page_size])
                pending = pending[page_size:]
        elif len(pending) >= 4000:
            write_browse(pending)
            pending = []
    if pending:
        write_browse(pending)
    if version >= 5:
        from app.services.snapshot_ranking import build_ranking_assets
        index["ranking"] = build_ranking_assets(directory, manifest, emit, version=2 if version >= 9 else 1)
    if version >= 2:
        from app.services.snapshot_search import build_search_assets
        index["search"] = build_search_assets(directory, manifest, emit, version=5 if version >= 9 else 4 if version >= 7 else 3 if version >= 5 else 2 if version >= 3 else 1,
                                             **({'ranking': index['ranking']} if version >= 9 else {}))
    if version >= 7:
        from app.services.snapshot_authors import build_author_assets
        index["search"]["authors"] = build_author_assets(directory, manifest, emit)
    if version in (4, 6, 8, 10):
        index["version"] = version - 1
        if version==10:
            from app.services.snapshot_descriptor import pack_descriptor, detach_search_lookup
            from app.services.snapshot_direct_tokens import direct_token_assets
            index['search']['direct']=direct_token_assets(directory,index['search'],emit)
            index = detach_search_lookup(index, manifest, emit)
            content=_json_bytes(pack_descriptor(index))
        else:
            content=_json_bytes(index)
        entry = emit("reader", content, manifest["paper_count"])
        return {"version": version, "paper_count": manifest["paper_count"], "index": entry}
    return index


def ensure_snapshot_reader(directory: Path, manifest: dict) -> dict:
    from app.services.snapshot import _json_bytes, _load_entry, _write_content, manifest_revision

    catalog, _ = _load_entry(directory, manifest["catalog"], "catalog")
    catalog["reader"] = build_reader_assets(directory, manifest, version=10)
    upgraded = {**manifest, "catalog": _write_content(directory, "catalog", _json_bytes(catalog))}
    upgraded["revision"] = manifest_revision(upgraded)
    return upgraded
