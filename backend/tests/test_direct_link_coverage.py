"""Distinguish direct reading entry points from confirmed free full text."""
import json
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
