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
EXPANDED_CARD_LIMIT = 1024
PAGE_HINT_SIZE = 20
PHRASE_HINT_SIZE = 100
SCOPE_HINT_GROUPS = 20


def _hint_ids(token, postings, titles, words, variants, paper_count, average_length,
              cards=None, phrases=None):
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
                    break
        if len(selected) == COMMON_CARD_LIMIT:
            break
    if cards is None:
        return selected
    # Venue/year neighborhoods reduce scattered card requests for the existing
    # filters. Large groups are selected first; all final results still undergo
    # the reader's exact filters, sort and page before any hint is displayed.
    scopes = defaultdict(list)
    for row in postings:
        card = cards[row[0]]
        if isinstance(card[3], int) and card[3] >= 2023:
            scopes[(card[2], card[3])].append(row)
    for _scope, candidates in sorted(scopes.items(), key=lambda item: (-len(item[1]), item[0]))[:SCOPE_HINT_GROUPS]:
        if len(candidates) < 50:
            continue
        for row in sorted(candidates, key=lambda row: (1 if row[3] else 3, scores[row[0]], -row[0]))[:PAGE_HINT_SIZE]:
            if row[0] not in seen:
                selected.append(row[0]); seen.add(row[0])
                if len(selected) == EXPANDED_CARD_LIMIT:
                    return selected
    rows_by_id = {row[0]: row for row in postings}
    # Reserve common source/year neighborhoods before larger phrase families
    # can exhaust the bound. Full result filtering and ordering are unchanged.
    for phrase, ids in sorted((phrases or {}).get(token, []), key=lambda item: (-len(item[1]), item[0])):
        candidates = [rows_by_id[pid] for pid in ids if pid in rows_by_id]
        for row in sorted(candidates, key=lambda row: (scores[row[0]], -row[0]))[:PHRASE_HINT_SIZE]:
            if row[0] not in seen:
                selected.append(row[0]); seen.add(row[0])
                if len(selected) == EXPANDED_CARD_LIMIT:
                    return selected
    return selected


def build_card_hints(database, directory, manifest, emit, average_length):
    """Emit title-vocabulary card hints from the producer's existing postings DB.

    Returns search.hints={bucket_chars:3,terms:{sha3:[cardhint entries]}}.
    Each file begins ['$cards',cardRows16], followed by [token,paperIDs].
    entry.count is the complete payload row count, including its dictionary.
    Same-token oversized groups split at card boundaries, so consumers merge
    all groups for a requested token. No published data or query results change.
    """
    from app.services.snapshot import MAX_FILE_BYTES, _json_bytes, _load_entry
    from app.services.snapshot_reader import FIELDS

    if not isinstance(average_length, (int, float)) or not math.isfinite(average_length) or average_length <= 0:
        raise ValueError("Invalid card hint average length")
    cards, titles, words, variants = {}, {}, {}, defaultdict(set)
    phrase_ids = defaultdict(set)
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
            stems = [stemmer(word) for word in title.split()]
            for width in (2, 3):
                for position in range(len(stems) - width + 1):
                    phrase_ids[tuple(stems[position:position + width])].add(pid)
    phrases = defaultdict(list)
    for phrase, ids in phrase_ids.items():
        if len(ids) >= 100:
            for token in set(phrase):
                phrases[token].append((phrase, ids))
    del phrase_ids
    database.execute("CREATE TABLE card_hint_tokens (token TEXT PRIMARY KEY)")
    database.executemany("INSERT INTO card_hint_tokens VALUES (?)", ((token,) for token in variants))
    index = {"bucket_chars": 3, "terms": {}}
    query = (
        "SELECT p.token,p.id,p.frequency,p.length,p.positions FROM postings p "
        "JOIN card_hint_tokens t ON t.token=p.token WHERE p.bucket=? ORDER BY p.token,p.id")
    for bucket, in database.execute(
        "SELECT DISTINCT p.bucket FROM postings p JOIN card_hint_tokens t ON t.token=p.token ORDER BY p.bucket"
    ):
        rows, dictionary, parts = [], {}, []
        size = len(_json_bytes([['$cards', []]]))

        def flush_part():
            nonlocal rows, dictionary, size
            if rows:
                payload = [['$cards', list(dictionary.values())], *rows]
                raw = _json_bytes(payload)
                if len(raw) > MAX_FILE_BYTES:
                    raise ValueError('Card hint dictionary exceeds reader asset limit')
                parts.append(emit('cardhint', raw, len(payload)))
            rows, dictionary = [], {}
            size = len(_json_bytes([['$cards', []]]))

        def append_group(token, ids):
            nonlocal rows, dictionary, size
            group = None
            for pid in ids:
                new_group = group is None
                added = len(str(pid)) + 1
                if new_group:
                    added += len(_json_bytes([token, []])) + 1
                if pid not in dictionary:
                    added += len(_json_bytes(cards[pid])) + 1
                if size + added > MAX_FILE_BYTES and rows:
                    flush_part(); group = None; new_group = True
                    added = len(str(pid)) + 1 + len(_json_bytes([token, []])) + 1
                    added += len(_json_bytes(cards[pid])) + 1
                if size + added > MAX_FILE_BYTES:
                    raise ValueError('Card hint row exceeds reader asset limit')
                if group is None:
                    group = [token, []]; rows.append(group)
                group[1].append(pid)
                dictionary.setdefault(pid, cards[pid]); size += added

        token, postings = None, []
        for current, pid, frequency, length, positions in database.execute(query, (bucket,)):
            if current != token:
                if token is not None:
                    append_group(token, _hint_ids(token, postings, titles, words, variants,
                                                 manifest["paper_count"], average_length, cards, phrases))
                token, postings = current, []
            postings.append((pid, frequency, length, json.loads(positions)))
        if token is not None:
            append_group(token, _hint_ids(token, postings, titles, words, variants,
                                         manifest["paper_count"], average_length, cards, phrases))
        flush_part()
        if parts:
            index["terms"][bucket] = parts
    return index
