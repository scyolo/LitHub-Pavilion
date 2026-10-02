import gzip
import json

from app.services.snapshot import export_snapshot, validate_snapshot
from app.services.snapshot_reader import (
    build_reader_assets,
    load_reader_descriptor,
    reader_entries,
)


def test_paged_reader_is_revision_bound_and_carries_ranking_metadata(
    session_factory, api_catalog, tmp_path
):
    manifest = export_snapshot(session_factory, tmp_path)
    pointer = build_reader_assets(tmp_path, manifest, version=6)
    assert pointer["version"] == 6 and "index" in pointer
    descriptor = load_reader_descriptor(tmp_path, {"reader": pointer})
    assert descriptor["version"] == 5
    assert descriptor["search"]["version"] == 3
    assert descriptor["search"]["bucket_chars"] == 3
    ranking = descriptor["ranking"]
    assert sum(part["count"] for part in ranking["parts"]) == manifest["paper_count"]
    ids = []
    for part in ranking["parts"]:
        previous = 0
        for row in json.loads(gzip.decompress((tmp_path / part["path"]).read_bytes())):
            assert len(row) == 9 and row[0] > 0
            previous += row[0]
            assert 0 <= row[1] < len(ranking["venues"])
            ids.append(previous)
        assert previous == part["max_id"]
    expected = sorted(
        p["id"]
        for part in manifest["chunks"]
        for p in json.loads((tmp_path / part["path"]).read_bytes())
    )
    assert sorted(ids) == expected
    entries = reader_entries({"reader": pointer}, tmp_path)
    assert all(part in entries for part in ranking["parts"])
    for parts in descriptor["search"]["terms"].values():
        for part in parts:
            for row in json.loads(
                gzip.decompress((tmp_path / part["path"]).read_bytes())
            ):
                assert len(row) == 5
                assert all(type(pos) is int and pos >= 0 for pos in row[4])
    validate_snapshot(tmp_path)
