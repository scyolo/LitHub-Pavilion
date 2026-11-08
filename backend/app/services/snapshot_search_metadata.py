"""Columnar search assets and candidate-only ranking companions."""
import json


def column_groups(records, columns, json_bytes, max_bytes, *, nested=False):
    """Stream token groups; split an oversized token at record boundaries.

    Record zero is its token; subsequent values already contain the paper ID
    followed by non-ID values. Each split restarts the positive ID deltas.
    """
    token = None
    values = [[] for _ in range(columns)]
    previous = 0
    size = 0

    def group():
        return [token, values] if nested else [token, *values]

    def value_size(value):
        if type(value) is int:
            return len(str(value))
        if isinstance(value, list) and all(type(item) is int for item in value):
            return 2 + sum(len(str(item)) for item in value) + max(0, len(value) - 1)
        return len(json_bytes(value))

    for record in records:
        if len(record) != columns + 1:
            raise ValueError("Invalid compact search record")
        current, pid, *fields = record
        if current != token:
            if token is not None:
                yield group()
            token, values, previous = current, [[] for _ in range(columns)], 0
            size = len(json_bytes(group()))
        if type(pid) is not int or pid <= previous:
            raise ValueError("Compact search IDs must increase within a token")
        row = [pid - previous, *fields]
        # Count a comma for every column even on its first value. This is a
        # conservative upper bound and keeps individual groups packable.
        added = sum(value_size(value) + 1 for value in row)
        if size + added > max_bytes - 3 and values[0]:
            yield group()
            values, previous = [[] for _ in range(columns)], 0
            size = len(json_bytes(group()))
            row[0] = pid
            added = sum(value_size(value) + 1 for value in row)
        if size + added > max_bytes - 3:
            raise ValueError("Compact search record exceeds asset size limit")
        for column, value in zip(values, row, strict=True):
            column.append(value)
        size += added
        previous = pid
    if token is not None:
        yield group()


def emit_column_groups(groups, prefix, emit, json_bytes, max_bytes):
    parts, rows, size = [], [], 2
    for group in groups:
        added = len(json_bytes(group)) + 1
        if size + added > max_bytes and rows:
            parts.append(emit(prefix, json_bytes(rows), len(rows)))
            rows, size = [], 2
        if size + added > max_bytes:
            raise ValueError("Compact search group exceeds asset size limit")
        rows.append(group)
        size += added
    if rows:
        parts.append(emit(prefix, json_bytes(rows), len(rows)))
    return parts


def prepare_ranking_table(database, directory, manifest, ranking):
    """Use precisely the dictionaries used by global ranking, disk-backed."""
    from app.services.snapshot_ranking import _ranking_records

    records, dictionaries = _ranking_records(directory, manifest)
    if ranking is None or any(ranking.get(key) != value for key, value in dictionaries.items()):
        raise ValueError("Search ranking dictionaries do not match public records")
    database.execute("CREATE TABLE search_rank (id INTEGER PRIMARY KEY, venue INTEGER, year INTEGER, "
                     "publication INTEGER, created INTEGER, citations INTEGER, directions TEXT, "
                     "pdf_status INTEGER, access INTEGER)")
    database.executemany("INSERT INTO search_rank VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         ([*row[:6], json.dumps(row[6], separators=(",", ":")), *row[7:]] for row in records))
    database.commit()


def ranking_companion_parts(database, bucket, emit, json_bytes, max_bytes):
    rows = database.execute(
        "SELECT p.token,p.id,r.venue,r.year,r.publication,r.created,r.citations,r.directions,r.pdf_status,r.access "
        "FROM postings p JOIN search_rank r ON r.id=p.id WHERE p.bucket=? ORDER BY p.token,p.id", (bucket,)
    )
    decoded = ((*row[:7], json.loads(row[7]), *row[8:]) for row in rows)
    groups = column_groups(decoded, 9, json_bytes, max_bytes, nested=True)
    return emit_column_groups(groups, "matchrank", emit, json_bytes, max_bytes)
