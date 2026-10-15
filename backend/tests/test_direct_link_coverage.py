"""Distinguish direct reading entry points from confirmed free full text."""
import json
import pytest
from app.api.serializers import paper_links
from app.services.snapshot import export_snapshot, validate_snapshot


def test_direct_coverage_is_not_the_oa_percentage(client, db, sample_paper, session_factory, tmp_path):
    assert paper_links(sample_paper)['official_url']
    assert not paper_links(sample_paper)['oa_url']
    dashboard = client.get('/api/stats/dashboard').json()
    assert dashboard['with_direct_link'] == dashboard['total'] == 1
    assert dashboard['with_oa_link'] == 0
    directory = tmp_path / 'snapshot'
    manifest = export_snapshot(session_factory, directory)
    catalog = json.loads((directory / manifest['catalog']['path']).read_text(encoding='utf8'))
    assert catalog['overview']['version'] == 3
    for scope in catalog['overview']['scopes']:
        assert scope['dashboard']['with_direct_link'] == scope['dashboard']['total']
    validate_snapshot(directory)


def test_unsafe_or_missing_urls_are_not_counted_as_direct_access(client, db, sample_paper):
    sample_paper.doi = None
    sample_paper.dblp_key = "unusable-legacy-identifier"
    sample_paper.publisher_key = None
    sample_paper.official_url = 'javascript:alert(1)'
    sample_paper.oa_url = 'http://127.0.0.1/private'
    sample_paper.arxiv_id = None
    db.commit()
    assert client.get('/api/stats/dashboard').json()['with_direct_link'] == 0

@pytest.mark.parametrize('version', [1, 2])
def test_old_overviews_and_256_row_readers_still_verify(session_factory, sample_paper, tmp_path, version):
    from app.services.snapshot import _json_bytes, _write_content, manifest_revision
    from app.services.snapshot_overview import OverviewBuilder
    from app.services.snapshot_reader import build_reader_assets, load_reader_descriptor

    manifest = export_snapshot(session_factory, tmp_path)
    catalog = json.loads((tmp_path / manifest['catalog']['path']).read_bytes())
    rows = [row for part in manifest['chunks'] for row in json.loads((tmp_path / part['path']).read_bytes())]
    overview = OverviewBuilder(catalog, manifest['generated_at'], version=version)
    overview.add(rows)
    catalog['overview'] = overview.result()
    catalog['reader'] = build_reader_assets(tmp_path, manifest, version=6, browse_chunk_size=None)
    assert 'browse_chunk_size' not in load_reader_descriptor(tmp_path, catalog)
    manifest['catalog'] = _write_content(tmp_path, 'catalog', _json_bytes(catalog))
    manifest['revision'] = manifest_revision(manifest)
    (tmp_path / 'manifest.json').write_bytes(_json_bytes(manifest))
    assert validate_snapshot(tmp_path) == manifest
