"""Disk-backed offline index; browsers fetch only queried token/title shards."""
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from collections import Counter
import re
from app.services.search_tokens import normalized_title, search_terms, stemmer


def compact_vocabulary_parts(vocabulary, emit, json_bytes, max_bytes):
    """Lossless sorted vocabulary front coding, with part-local prefixes.

    One file contains one marker row: [$vocab, prefixCodes, joinedSuffixes, DF].
    A prefix is encoded by a Unicode codepoint length+32. Each suffix is ASCII
    alphanumeric and separated by one space, so decoding has no escaping work.
    """
    parts = []
    codes, suffixes, frequencies = [], [], []
    previous = ''
    conservative_size = 32

    def payload():
        return [['$vocab', ''.join(codes), ' '.join(suffixes), frequencies]]

    for term, frequency in sorted(vocabulary.items()):
        if (not isinstance(term, str) or not re.fullmatch('[a-z0-9]+', term)
                or type(frequency) is not int or frequency < 1):
            raise ValueError('Invalid compact vocabulary record')
        common = 0
        while common < min(len(previous), len(term)) and previous[common] == term[common]:
            common += 1
        if common > 0x10ffff - 32:
            raise ValueError('Vocabulary prefix exceeds encoding limit')
        suffix = term[common:]
        # Full-word size bounds any suffix. A JSON-escaped codepoint can use
        # twelve ASCII bytes, while UTF-8 encoding requires no more than four.
        added = len(term) + len(str(frequency)) + 15
        if conservative_size + added > max_bytes and codes:
            content = json_bytes(payload())
            if len(content) > max_bytes:
                raise ValueError('Compact vocabulary exceeds asset limit')
            parts.append(emit('vocabulary', content, 1))
            codes, suffixes, frequencies, previous, conservative_size = [], [], [], '', 32
            common, suffix = 0, term
        if conservative_size + added > max_bytes:
            raise ValueError('Vocabulary record exceeds asset size limit')
        if not suffix:
            raise ValueError('Vocabulary records must be strictly sorted and unique')
        codes.append(chr(common + 32))
        suffixes.append(suffix)
        frequencies.append(frequency)
        conservative_size += added
        previous = term
    if codes:
        content = json_bytes(payload())
        if len(content) > max_bytes:
            raise ValueError('Compact vocabulary exceeds asset limit')
        parts.append(emit('vocabulary', content, 1))
    return parts


def build_search_assets(directory, manifest, emit, *, version=1, ranking=None):
    from app.services.snapshot import _load_entry, _json_bytes, MAX_FILE_BYTES

    index = {"version": version, "terms": {}, "titles": {}, "average_length": 1}
    if version not in range(1, 6):
        raise ValueError("Unsupported search version")
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
            if version >= 5:
                from app.services.snapshot_search_metadata import prepare_ranking_table

                prepare_ranking_table(database, directory, manifest, ranking)
                index["metadata"] = {"bucket_chars": 3, "terms": {}}
            for section, table, columns, prefix in [
                ("terms", "postings", "token,id,frequency,length,positions" if version >= 3 else "token,id,frequency,length", "search"),
                ("titles", "titles", "title,id", "titles"),
            ]:
                for (bucket,) in database.execute(f"SELECT DISTINCT bucket FROM {table} ORDER BY bucket"):
                    if section == "terms" and version >= 5:
                        from app.services.snapshot_search_metadata import (
                            column_groups, emit_column_groups, ranking_companion_parts,
                        )

                        source = database.execute(
                            "SELECT token,id,frequency,length,positions FROM postings "
                            "WHERE bucket=? ORDER BY token,id", (bucket,))
                        decoded = ((*row[:4], json.loads(row[4])) for row in source)
                        groups = column_groups(decoded, 4, _json_bytes, MAX_FILE_BYTES)
                        index["terms"][bucket] = emit_column_groups(groups, "search", emit, _json_bytes, MAX_FILE_BYTES)
                        index["metadata"]["terms"][bucket] = ranking_companion_parts(
                            database, bucket, emit, _json_bytes, MAX_FILE_BYTES)
                        continue
                    rows, size, parts = [], 2, []
                    for row in database.execute(f"SELECT {columns} FROM {table} WHERE bucket=? ORDER BY 1,2", (bucket,)):
                        if section == "terms" and version >= 3:
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
            if version>=5:
                from app.services.snapshot_card_hints import build_card_hints
                index['hints']=build_card_hints(database,directory,manifest,emit,total_length/max(1,manifest['paper_count']) or 1)
    index["average_length"] = total_length / max(1, manifest["paper_count"]) or 1
    if version >= 2:
        index['vocabulary'] = []
        if version >= 5:
            index['vocabulary'] = compact_vocabulary_parts(vocabulary, emit, _json_bytes, MAX_FILE_BYTES)
            return index
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
