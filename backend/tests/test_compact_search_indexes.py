"""Compact cold-search assets retain old row semantics and source IDs."""
import json

import pytest

from app.services.snapshot import _json_bytes, _write_content
from app.services.snapshot_ranking import build_ranking_assets
from app.services.snapshot_search import build_search_assets
from app.services.snapshot_search_metadata import column_groups, emit_column_groups


@pytest.fixture()
def corpus(tmp_path):
    papers = [
        {"id": 11, "title": "Learning model", "abstract": "Learning model", "venue": "A", "year": 2024,
         "publication_date": "2024-03-04", "created_at": "2024-03-05T00:00:00Z", "citation_count": 7,
         "directions": ["llm", "agent"], "pdf_status": "closed", "oa_url": None},
        {"id": 23, "title": "Other model", "abstract": "", "venue": "B", "year": 2023,
         "publication_date": None, "created_at": "2024-03-05T00:00:00Z", "citation_count": 1,
         "directions": ["llm"], "pdf_status": "pending", "oa_url": "https://example.org/open"},
    ]
    from app.services.snapshot_reader import FIELDS
    papers=[{**{field:None for field in FIELDS},**paper} for paper in papers]
    entry = {**_write_content(tmp_path, "papers", _json_bytes(papers)), "count": len(papers)}
    return {"paper_count": len(papers), "chunks": [entry]}


def collector():
    payloads = {}

    def emit(prefix, raw, count):
        import hashlib

        digest = hashlib.sha256(raw).hexdigest()
        path = f"{prefix}-{digest}.json.gz"
        payloads[path] = raw
        return {"path": path, "sha256": digest, "count": count}

    return emit, payloads


def decode_postings(groups):
    rows = []
    for token, deltas, frequencies, lengths, positions in groups:
        pid = 0
        for delta, frequency, length, offsets in zip(deltas, frequencies, lengths, positions, strict=True):
            pid += delta
            rows.append([token, pid, frequency, length, offsets])
    return rows


def decode_rank(columns):
    rows, pid = [], 0
    for row in zip(*columns, strict=True):
        pid += row[0]
        rows.append([pid, *row[1:]])
    return rows


def test_old_ranking_bytes_and_columnar_ranking_decode_identically(corpus, tmp_path):
    old_emit, old_files = collector()
    old = build_ranking_assets(tmp_path, corpus, old_emit)
    expected = [[11, 0, 2024, 1, 0, 7, [0, 1], 0, 0], [12, 1, 2023, 0, 0, 1, [1], 1, 1]]
    assert old["version"] == 1
    assert old["venues"] == ["A", "B"]
    assert old["directions"] == ["agent", "llm"]
    assert old_files[old["parts"][0]["path"]] == _json_bytes(expected)
    new_emit, new_files = collector()
    new = build_ranking_assets(tmp_path, corpus, new_emit, version=2)
    assert new["version"] == 2
    for key in ("venues", "directions", "pdf_statuses"):
        assert old[key] == new[key]
    columns = json.loads(new_files[new["parts"][0]["path"]])
    assert len(columns) == 9
    assert decode_rank(columns) == [[11, *expected[0][1:]], [23, *expected[1][1:]]]
    assert new["parts"][0]["count"] == 2


def test_compact_postings_and_candidate_metadata_preserve_full_old_rows(corpus, tmp_path):
    emit, files = collector()
    ranking = build_ranking_assets(tmp_path, corpus, emit, version=2)
    old = build_search_assets(tmp_path, corpus, emit, version=4)
    new = build_search_assets(tmp_path, corpus, emit, version=5, ranking=ranking)
    old_rows = sorted(row for parts in old["terms"].values() for entry in parts
                      for row in json.loads(files[entry["path"]]))
    assert old_rows == [["learn", 11, 9, 4, [0]], ["model", 11, 9, 4, [1]],
                        ["model", 23, 8, 2, [1]], ["other", 23, 8, 2, [0]]]
    compact = sorted(row for parts in new["terms"].values() for entry in parts
                     for row in decode_postings(json.loads(files[entry["path"]])))
    assert compact == old_rows
    assert old["titles"] == new["titles"]
    from test_compact_vocabulary import decoded
    assert [row for entry in old['vocabulary'] for row in json.loads(files[entry['path']])] == decoded(
        [files[entry['path']] for entry in new['vocabulary']])
    assert old["average_length"] == new["average_length"]
    global_rows = {row[0]: row for entry in ranking["parts"]
                   for row in decode_rank(json.loads(files[entry["path"]]))}
    companions = {}
    for parts in new["metadata"]["terms"].values():
        for entry in parts:
            groups = json.loads(files[entry["path"]])
            assert len(groups) == entry["count"]
            for token, columns in groups:
                companions.setdefault(token, []).extend(decode_rank(columns))
    for token, rows in companions.items():
        assert [row[0] for row in rows] == [row[1] for row in old_rows if row[0] == token]
        assert all(row == global_rows[row[0]] for row in rows)
    assert companions["learn"][0][0] == 11
    assert len(companions["learn"]) == 1  # no unrelated global metadata


def test_old_search_formats_keep_raw_rows_and_have_no_candidate_metadata(corpus, tmp_path):
    emit, files = collector()
    for version in (1, 2, 3, 4):
        result = build_search_assets(tmp_path, corpus, emit, version=version)
        assert "metadata" not in result
        rows = sorted(row for parts in result["terms"].values() for entry in parts
                      for row in json.loads(files[entry["path"]]))
        expected = [["learn", 11, 9, 4, [0]], ["model", 11, 9, 4, [1]],
                    ["model", 23, 8, 2, [1]], ["other", 23, 8, 2, [0]]]
        if version < 3:
            expected = [row[:4] for row in expected]
        assert rows == expected


def test_split_token_groups_restart_ids_and_respect_size_budget():
    records = [("term", i * 100, 8, 50, [0, 5]) for i in range(1, 41)]
    groups = list(column_groups(records, 4, _json_bytes, 150))
    assert len(groups) > 1
    emit, files = collector()
    parts = emit_column_groups(groups, "search", emit, _json_bytes, 150)
    assert all(len(raw) <= 150 for raw in files.values())
    decoded = [row for part in parts for row in decode_postings(json.loads(files[part["path"]]))]
    assert decoded == [list(row) for row in records]


def test_companion_rejects_dictionary_mismatch_before_emitting(corpus, tmp_path):
    emit, _ = collector()
    ranking = build_ranking_assets(tmp_path, corpus, emit, version=2)
    with pytest.raises(ValueError, match="dictionaries"):
        build_search_assets(tmp_path, corpus, emit, version=5, ranking={**ranking, "venues": ["B", "A"]})
