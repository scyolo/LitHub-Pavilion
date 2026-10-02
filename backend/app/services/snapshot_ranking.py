"""Compact, revision-bound filtering/sort rows; no titles, abstracts or URLs."""

from datetime import datetime, timezone

from app.publication import publication_sort_key


def build_ranking_assets(directory, manifest, emit):
    from app.services.snapshot import _json_bytes, _load_entry

    rows = []
    for entry in manifest["chunks"]:
        papers, _ = _load_entry(directory, entry, "papers")
        for paper in papers:
            try:
                dt = datetime.fromisoformat(
                    (paper["created_at"] or "").replace("Z", "+00:00")
                )
                created = int(
                    dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp() * 1000
                )
            except (TypeError, ValueError, OverflowError):
                created = 0
            rows.append(
                [
                    paper["id"],
                    paper["venue"],
                    paper["year"],
                    publication_sort_key(paper),
                    created,
                    paper["citation_count"] or 0,
                    sorted(set(paper["directions"])),
                    paper["pdf_status"],
                    int(bool(paper["oa_url"])),
                ]
            )
    rows.sort(key=lambda row: row[0])
    venues = sorted({row[1] for row in rows})
    directions = sorted({code for row in rows for code in row[6]})
    statuses = sorted({row[7] for row in rows}, key=lambda value: value or "")
    dictionaries = [
        dict((value, i) for i, value in enumerate(values))
        for values in (
            venues,
            sorted({row[3] for row in rows}),
            sorted({row[4] for row in rows}),
            directions,
            statuses,
        )
    ]
    vi, pi, ci, di, si = dictionaries
    parts = []
    # Bound decoded JSON well below 8 MiB, and keep cold-start fanout small.
    for start in range(0, len(rows), 100000):
        source = rows[start : start + 100000]
        encoded, previous = [], 0
        for row in source:
            encoded.append(
                [
                    row[0] - previous,
                    vi[row[1]],
                    row[2],
                    pi[row[3]],
                    ci[row[4]],
                    row[5],
                    [di[code] for code in row[6]],
                    si[row[7]],
                    row[8],
                ]
            )
            previous = row[0]
        part = emit("ranking", _json_bytes(encoded), len(encoded))
        parts.append({**part, "min_id": source[0][0], "max_id": source[-1][0]})
    return {
        "version": 1,
        "parts": parts,
        "venues": venues,
        "directions": directions,
        "pdf_statuses": statuses,
    }
