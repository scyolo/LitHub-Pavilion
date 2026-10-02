import gzip
import hashlib
import json
import pytest

from app.services.snapshot_reader import FIELDS, build_reader_assets, load_reader_descriptor


def test_reader_preserves_titles_links_and_exact_details(session_factory, api_catalog, tmp_path):
    from app.services.snapshot import export_snapshot

    manifest = export_snapshot(session_factory, tmp_path, chunk_size=2)
    index = build_reader_assets(tmp_path, manifest)
    assert index["paper_count"] == manifest["paper_count"]
    assert sum(entry["count"] for entry in index["browse"]) == manifest["paper_count"]
    expected = []
    for source, detail in zip(manifest["chunks"], index["details"], strict=True):
        raw = gzip.decompress((tmp_path / detail["path"]).read_bytes())
        assert raw == (tmp_path / source["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == detail["sha256"]
        rows = json.loads(raw)
        assert detail["min_id"] == min(row["id"] for row in rows)
        assert detail["max_id"] == max(row["id"] for row in rows)
        expected.extend([[row[field] for field in FIELDS] for row in rows])
    actual = []
    for entry in index["browse"]:
        raw = gzip.decompress((tmp_path / entry["path"]).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        actual.extend(json.loads(raw))
    assert actual == expected
    assert build_reader_assets(tmp_path, manifest) == index


@pytest.mark.parametrize("kind", ["browse", "details", "terms", "titles"])
def test_reader_rejects_corrupt_assets(session_factory, sample_paper, tmp_path, kind):
    from app.services.snapshot import export_snapshot, validate_snapshot

    manifest = export_snapshot(session_factory, tmp_path)
    catalog = json.loads((tmp_path / manifest["catalog"]["path"] ).read_bytes())
    reader = load_reader_descriptor(tmp_path, catalog)
    entries = reader[kind] if kind in ("browse", "details") else next(iter(reader["search"][kind].values()))
    (tmp_path / entries[0]["path"]).write_bytes(gzip.compress(b"[]"))
    with pytest.raises(ValueError, match="digest|match"):
        validate_snapshot(tmp_path)
    with pytest.raises(ValueError):
        build_reader_assets(tmp_path, manifest, version=catalog["reader"]["version"])


def test_search_assets_index_abstracts_and_title_identity(session_factory, sample_paper, tmp_path):
    from app.services.snapshot import export_snapshot
    from app.services.search_tokens import normalized_title, stemmer

    manifest = export_snapshot(session_factory, tmp_path)
    reader = build_reader_assets(tmp_path, manifest)
    titles = [row for parts in reader["search"]["titles"].values() for entry in parts
              for row in json.loads(gzip.decompress((tmp_path / entry["path"]).read_bytes()))]
    assert [normalized_title(sample_paper.title), sample_paper.id] in titles
    assert [stemmer(word) for word in ["models", "decoding", "relational", "skies", "generously"]] == ["model", "decod", "relat", "ski", "gener"]


def test_detached_reader_is_small_and_validated(session_factory, sample_paper, tmp_path):
    from app.services.snapshot import export_snapshot
    from app.services.snapshot_reader import reader_entries, load_reader_descriptor
    manifest=export_snapshot(session_factory,tmp_path)
    reader=build_reader_assets(tmp_path,manifest,version=4)
    assert reader['version']==4 and len(json.dumps(reader))<400
    catalog={'reader':reader}
    descriptor=load_reader_descriptor(tmp_path,catalog)
    assert descriptor['version']==3 and descriptor['paper_count']==manifest['paper_count']
    paths={e['path'] for e in reader_entries(catalog,tmp_path)}
    assert reader['index']['path'] in paths
    assert any(p.startswith('browse-') for p in paths)
    (tmp_path/reader['index']['path']).write_bytes(gzip.compress(b'{}'))
    with pytest.raises(ValueError,match='digest'):
        load_reader_descriptor(tmp_path,catalog)
