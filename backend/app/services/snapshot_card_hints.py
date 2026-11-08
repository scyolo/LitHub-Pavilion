"""Verified card hints reduce scattered first-page fetches without selecting results.

The reader still computes the complete filtered result and its order. Hints are
only an ID-to-display-row cache; non-hinted page IDs use ordinary browse assets.
"""
import json
import math
from collections import defaultdict

from app.services.search_tokens import normalized_title, stemmer


RARE_CARD_LIMIT = 1024
COMMON_CARD_LIMIT = 128
PAGE_HINT_SIZE = 20


def _hint_ids(token, postings, titles, words, variants, paper_count, average_length):
    """All rare records, otherwise a bounded union of generic name variants."""
    if len(postings) <= RARE_CARD_LIMIT:
        return [row[0] for row in postings]
    idf = max(1e-6, math.log((paper_count - len(postings) + 0.5) / (len(postings) + 0.5)))
    scores = {}
    for pid, frequency, length, positions in postings:
        scores[pid] = -idf * frequency * 2.2 / (
            frequency + 1.2 * (0.25 + 0.75 * length / average_length))
    # Preserve the unscoped, one-stem result's first page before spending the
    # remaining bound on raw spelling variants. Title phrase positions make
    # learning/learned/learn share this base priority in the live reader.
    base = sorted(postings, key=lambda row: (1 if row[3] else 3, scores[row[0]], -row[0]))
    selected = list(dict.fromkeys(row[0] for row in base[:PAGE_HINT_SIZE]))
    seen = set(selected)
    for word in sorted(variants[token]):
        ranked = sorted(postings, key=lambda row: (
            0 if titles[row[0]] == word else 1 if word in words[row[0]] else 2 if row[3] else 3,
            scores[row[0]], -row[0]))
        for row in ranked[:PAGE_HINT_SIZE]:
            if row[0] not in seen:
                selected.append(row[0]); seen.add(row[0])
                if len(selected) == COMMON_CARD_LIMIT:
                    return selected
    return selected


def build_card_hints(database, directory, manifest, emit, average_length):
    """Emit title-vocabulary card hints from the producer's existing postings DB.

    Returns search.hints={bucket_chars:3,terms:{sha3:[cardhint entries]}}.
    Every file is an array of [token, cardRows16]; entry.count is group count.
    Same-token oversized groups split at card boundaries, so consumers merge
    all groups for a requested token. No published data or query results change.
    """
    from app.services.snapshot import MAX_FILE_BYTES, _json_bytes, _load_entry
    from app.services.snapshot_reader import FIELDS

    if not isinstance(average_length, (int, float)) or not math.isfinite(average_length) or average_length <= 0:
        raise ValueError("Invalid card hint average length")
    cards, titles, words, variants = {}, {}, {}, defaultdict(set)
    for entry in manifest["chunks"]:
        papers, _ = _load_entry(directory, entry, "papers")
        for paper in papers:
            pid = paper["id"]
            title = normalized_title(paper["title"])
            cards[pid] = [paper[field] for field in FIELDS]
            titles[pid] = title
            words[pid] = set(title.split())
            for word in words[pid]:
                variants[stemmer(word)].add(word)
    database.execute("CREATE TABLE card_hint_tokens (token TEXT PRIMARY KEY)")
    database.executemany("INSERT INTO card_hint_tokens VALUES (?)", ((token,) for token in variants))
    index = {"bucket_chars": 3, "terms": {}}
    query = (
        "SELECT p.token,p.id,p.frequency,p.length,p.positions FROM postings p "
        "JOIN card_hint_tokens t ON t.token=p.token WHERE p.bucket=? ORDER BY p.token,p.id")
    for bucket, in database.execute(
        "SELECT DISTINCT p.bucket FROM postings p JOIN card_hint_tokens t ON t.token=p.token ORDER BY p.bucket"
    ):
        rows, size, parts = [], 2, []

        def append_group(token, ids):
            nonlocal rows, size
            group = [token, []]
            group_size = len(_json_bytes(group))
            for pid in ids:
                row = cards[pid]
                added = len(_json_bytes(row)) + 1
                if group_size + added > MAX_FILE_BYTES - 3 and group[1]:
                    append_part(group)
                    group, group_size = [token, []], len(_json_bytes([token, []]))
                if group_size + added > MAX_FILE_BYTES - 3:
                    raise ValueError("Card hint row exceeds reader asset limit")
                group[1].append(row); group_size += added
            if group[1]:
                append_part(group)

        def append_part(group):
            nonlocal rows, size
            added = len(_json_bytes(group)) + 1
            if size + added > MAX_FILE_BYTES and rows:
                parts.append(emit("cardhint", _json_bytes(rows), len(rows)))
                rows, size = [], 2
            if size + added > MAX_FILE_BYTES:
                raise ValueError("Card hint group exceeds reader asset limit")
            rows.append(group); size += added

        token, postings = None, []
        for current, pid, frequency, length, positions in database.execute(query, (bucket,)):
            if current != token:
                if token is not None:
                    append_group(token, _hint_ids(token, postings, titles, words, variants,
                                                 manifest["paper_count"], average_length))
                token, postings = current, []
            postings.append((pid, frequency, length, json.loads(positions)))
        if token is not None:
            append_group(token, _hint_ids(token, postings, titles, words, variants,
                                         manifest["paper_count"], average_length))
        if rows:
            parts.append(emit("cardhint", _json_bytes(rows), len(rows)))
        if parts:
            index["terms"][bucket] = parts
    return index
