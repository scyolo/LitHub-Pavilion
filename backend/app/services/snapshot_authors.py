"""Bounded author-token shards derived from every public authorship slot."""
import hashlib
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def build_author_assets(directory, manifest, emit):
    from app.services.author_search import normalize_author_name
    from app.services.snapshot import MAX_FILE_BYTES, _json_bytes, _load_entry

    index = {"version": 1, "bucket_chars": 3, "terms": {}}
    with tempfile.TemporaryDirectory(prefix="lithub-authors-") as temporary:
        with closing(sqlite3.connect(Path(temporary) / "index.sqlite")) as database:
            database.execute("CREATE TABLE postings (bucket TEXT, token TEXT, name TEXT, id INTEGER)")
            for entry in manifest["chunks"]:
                papers, _ = _load_entry(directory, entry, "papers")
                rows = []
                for paper in papers:
                    for name in dict.fromkeys(author["name"] for author in paper["authors"]):
                        normalized = normalize_author_name(name)
                        rows.extend((hashlib.sha256(token.encode()).hexdigest()[:3], token, name, paper["id"])
                                    for token in set(normalized.split()))
                database.executemany("INSERT INTO postings VALUES (?, ?, ?, ?)", rows)
                database.commit()
            database.execute("CREATE INDEX author_order ON postings(bucket, token, name, id)")
            for bucket, in database.execute("SELECT DISTINCT bucket FROM postings ORDER BY bucket"):
                parts, rows, size = [], [], 2
                for token, name, pid in database.execute(
                    "SELECT DISTINCT token,name,id FROM postings WHERE bucket=? ORDER BY token,name,id", (bucket,)
                ):
                    # Group one author/token's paper IDs so common names don't
                    # repeat their display string for every publication.
                    if rows and rows[-1][0] == token and rows[-1][1] == name:
                        added = len(_json_bytes(pid)) + 1
                        if size + added <= MAX_FILE_BYTES:
                            rows[-1][2].append(pid)
                            size += added
                            continue
                    row = [token, name, [pid]]
                    added = len(_json_bytes(row)) + 1
                    if size + added > MAX_FILE_BYTES and rows:
                        parts.append(emit("author", _json_bytes(rows), len(rows)))
                        rows, size = [], 2
                    if added + 2 > MAX_FILE_BYTES:
                        raise ValueError("Author name exceeds the reader asset limit")
                    rows.append(row)
                    size += added
                if rows:
                    parts.append(emit("author", _json_bytes(rows), len(rows)))
                index["terms"][bucket] = parts
    return {"version": 1, "bucket_chars": 3,
            "index": emit("authors", _json_bytes(index), manifest["paper_count"])}
