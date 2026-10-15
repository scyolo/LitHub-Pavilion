"""Cold relevance search keeps exact membership without downloading sort rows."""

import gzip
import hashlib
import json

import pytest

from app.services.snapshot import (
    _atomic_write,
    _json_bytes,
    _write_content,
    export_snapshot,
    manifest_revision,
    validate_snapshot,
)
from app.services.snapshot_reader import build_reader_assets, load_reader_descriptor


def _replace_reader(directory, manifest, descriptor):
    raw = _json_bytes(descriptor)
    digest = hashlib.sha256(raw).hexdigest()
    entry = {"path": f"reader-{digest}.json.gz", "sha256": digest, "count": manifest["paper_count"]}
    _atomic_write(directory / entry["path"], gzip.compress(raw, mtime=0))
    catalog = json.loads((directory / manifest["catalog"]["path"]).read_bytes())
    catalog["reader"] = {"version": 6, "paper_count": manifest["paper_count"], "index": entry}
    manifest = {**manifest, "catalog": _write_content(directory, "catalog", _json_bytes(catalog))}
    manifest["revision"] = manifest_revision(manifest)
    _atomic_write(directory / "manifest.json", _json_bytes(manifest))
    return manifest


def test_exact_membership_runs_are_sparse_safe_and_do_not_change_sort_assets(
    session_factory, api_catalog, tmp_path
):
    original = export_snapshot(session_factory, tmp_path)
    base = json.loads((tmp_path / original["chunks"][0]["path"]).read_bytes())[0]
    ids = [1, 2, 5, 6, 7, 1_000_000_003]
    rows = [{**base, "id": value, "title": f"Membership record {value}"} for value in ids]
    chunk = {**_write_content(tmp_path, "papers", _json_bytes(rows)), "count": len(rows)}
    manifest = {**original, "paper_count": len(rows), "chunks": [chunk]}
    pointer = build_reader_assets(tmp_path, manifest, version=6)
    reader = load_reader_descriptor(tmp_path, {"reader": pointer})
    assert reader["ranking"]["version"] == 1  # Optional metadata is safe for deployed old readers.
    assert reader["ranking"].get("id_runs") == [1, 2, 3, 3, 999_999_996, 1]
    legacy = load_reader_descriptor(tmp_path, {
        "reader": build_reader_assets(tmp_path, manifest, version=6, include_rank_membership=False)
    })
    assert "id_runs" not in legacy["ranking"]
    assert {k: v for k, v in reader["ranking"].items() if k != "id_runs"} == legacy["ranking"]
    assert reader["browse"] == legacy["browse"]
    assert reader["search"] == legacy["search"]


def test_published_reader_without_optional_membership_still_validates(
    session_factory, api_catalog, tmp_path
):
    manifest = export_snapshot(session_factory, tmp_path)
    pointer = build_reader_assets(tmp_path, manifest, version=6, include_rank_membership=False)
    legacy = load_reader_descriptor(tmp_path, {"reader": pointer})
    assert "id_runs" not in legacy["ranking"]
    manifest = _replace_reader(tmp_path, manifest, legacy)
    assert validate_snapshot(tmp_path) == manifest


def test_membership_is_rebuilt_from_all_public_rows_not_trusted_as_an_assertion(
    session_factory, api_catalog, tmp_path
):
    manifest = export_snapshot(session_factory, tmp_path)
    catalog = json.loads((tmp_path / manifest["catalog"]["path"]).read_bytes())
    reader = load_reader_descriptor(tmp_path, catalog)
    assert "id_runs" in reader["ranking"]
    assert sum(reader["ranking"]["id_runs"][1::2]) == manifest["paper_count"]
    reader["ranking"]["id_runs"][0] += 1
    _replace_reader(tmp_path, manifest, reader)
    with pytest.raises(ValueError, match="reader index does not match"):
        validate_snapshot(tmp_path)
