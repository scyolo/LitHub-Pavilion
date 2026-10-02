"""Disk-backed offline index; browsers fetch only queried token/title shards."""
import hashlib
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from collections import Counter
import re
from app.services.search_tokens import normalized_title, search_terms, stemmer


def build_search_assets(directory, manifest, emit, *, version=1):
    from app.services.snapshot import _load_entry, _json_bytes, MAX_FILE_BYTES

    index = {"version": version, "terms": {}, "titles": {}, "average_length": 1}
    if version >= 3:
        index["bucket_chars"] = 3
    vocabulary = Counter()
    total_length = 0
    with tempfile.TemporaryDirectory(prefix="lithub-search-") as temporary:
        with closing(sqlite3.connect(Path(temporary) / "index.sqlite")) as database:
            database.execute("CREATE TABLE postings (bucket TEXT, token TEXT, id INTEGER, frequency INTEGER, length INTEGER, positions TEXT)")
            database.execute("CREATE TABLE titles (bucket TEXT, title TEXT, id INTEGER)")
            for entry in manifest["chunks"]:
                papers, _ = _load_entry(directory, entry, "papers")
                for paper in papers:
                    terms, length = search_terms(paper)
                    total_length += length
                    positions = {}
                    if version >= 3:
                        for offset, term in enumerate(re.findall(r'[a-z0-9]+', normalized_title(paper['title']))):
                            positions.setdefault(stemmer(term), []).append(offset)
                    database.executemany("INSERT INTO postings VALUES (?, ?, ?, ?, ?, ?)",
                        ((hashlib.sha256(token.encode()).hexdigest()[:3 if version >= 3 else 2], token, paper["id"], frequency, length,
                          _json_bytes(positions.get(token, [])).decode()) for token, frequency in terms.items()))
                    title = normalized_title(paper["title"])
                    if version >= 2:
                        vocabulary.update({stemmer(term) for term in re.findall(r'[a-z0-9]+', title)})
                    database.execute("INSERT INTO titles VALUES (?, ?, ?)",
                        (hashlib.sha256(title.encode()).hexdigest()[:2], title, paper["id"]))
                database.commit()
            database.execute("CREATE INDEX postings_order ON postings(bucket, token, id)")
            database.execute("CREATE INDEX titles_order ON titles(bucket, title, id)")
            for section, table, columns, prefix in [
                ("terms", "postings", "token,id,frequency,length,positions" if version >= 3 else "token,id,frequency,length", "search"),
                ("titles", "titles", "title,id", "titles"),
            ]:
                for (bucket,) in database.execute(f"SELECT DISTINCT bucket FROM {table} ORDER BY bucket"):
                    rows, size, parts = [], 2, []
                    for row in database.execute(f"SELECT {columns} FROM {table} WHERE bucket=? ORDER BY 1,2", (bucket,)):
                        if section == "terms" and version >= 3:
                            import json
                            row = (*row[:4], json.loads(row[4]))
                        added = len(_json_bytes(row)) + 1
                        if size + added > MAX_FILE_BYTES and rows:
                            parts.append(emit(prefix, _json_bytes(rows), len(rows)))
                            rows, size = [], 2
                        rows.append(row)
                        size += added
                    if rows:
                        parts.append(emit(prefix, _json_bytes(rows), len(rows)))
                    index[section][bucket] = parts
    index["average_length"] = total_length / max(1, manifest["paper_count"]) or 1
    if version >= 2:
        index['vocabulary'] = []
        rows, size = [], 2
        for row in sorted(vocabulary.items()):
            added = len(_json_bytes(row)) + 1
            if size + added > MAX_FILE_BYTES and rows:
                index['vocabulary'].append(emit('vocabulary', _json_bytes(rows), len(rows)))
                rows, size = [], 2
            rows.append(row)
            size += added
        if rows:
            index['vocabulary'].append(emit('vocabulary', _json_bytes(rows), len(rows)))
    return index
