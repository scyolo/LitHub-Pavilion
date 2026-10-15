"""ACM's 2026 OA transition is article evidence, not a search-link shortcut."""
import json

import pytest

from app.api.serializers import paper_links
from app.services.open_access import publisher_open_url


@pytest.mark.parametrize('metadata', [
    {'doi': '10.1145/3544548.3580688'},
    {'doi': 'https://doi.org/10.1145/3544548.3580688'},
    {'official_url': 'https://doi.org/10.1145/3544548.3580688'},
    {'publisher_key': 'https://dl.acm.org/doi/abs/10.1145/3544548.3580688'},
    {'official_url': 'https://dl.acm.org/doi/pdf/10.1145/3544548.3580688'},
])
def test_acm_published_articles_have_open_landing_pages(metadata):
    link = publisher_open_url(**metadata)
    assert link is not None
    assert link.source == 'ACM Open'
    assert link.url == 'https://dl.acm.org/doi/10.1145/3544548.3580688'


@pytest.mark.parametrize('metadata', [
    {'doi': '10.11450/3544548.3580688'},
    {'doi': '10.1145/not-an-article'},
    {'official_url': 'https://dl.acm.org/action/doSearch?AllField=learning'},
    {'official_url': 'https://dl.acm.org/toc/pacmhci/2025/9/2'},
    {'official_url': 'https://dl.acm.org.evil.example/doi/10.1145/3544548.3580688'},
    {'official_url': 'https://user:password@dl.acm.org/doi/10.1145/3544548.3580688'},
    {'doi': '10.1109/valid.1', 'official_url': 'https://dl.acm.org/doi/10.1145/3544548.3580688'},
    {'doi': '10.1145/111.222', 'official_url': 'https://dl.acm.org/doi/10.1145/333.444'},
])
def test_acm_rejects_unsafe_nonarticle_and_conflicting_evidence(metadata):
    link = publisher_open_url(**metadata)
    if metadata.get('doi') == '10.1145/111.222':
        assert link.url == 'https://dl.acm.org/doi/10.1145/111.222'
    else:
        assert link is None


def test_acm_policy_updates_api_filters_and_export_without_mutating_metadata(client, db, sample_paper, session_factory, tmp_path):
    from app.services.snapshot import export_snapshot

    sample_paper.doi = '10.1145/3544548.3580688'
    sample_paper.official_url = 'https://doi.org/' + sample_paper.doi
    db.commit()
    assert paper_links(sample_paper)['oa_url'].startswith('https://dl.acm.org/doi/')
    assert client.get('/api/stats/dashboard').json()['with_oa_link'] == 1
    assert client.get('/api/papers', params={'access': 'oa'}).json()['total'] == 1
    manifest = export_snapshot(session_factory, tmp_path / 'snapshot')
    rows = json.loads((tmp_path / 'snapshot' / manifest['chunks'][0]['path']).read_text(encoding='utf8'))
    assert rows[0]['oa_url'] == paper_links(sample_paper)['oa_url']
    db.refresh(sample_paper)
    assert sample_paper.oa_url is None


def test_full_local_repair_is_idempotent_and_preserves_existing_links(db, sample_paper, session_factory):
    from app.services.links_backfill import backfill_local_links

    sample_paper.doi = '10.1145/3544548.3580688'
    db.commit()
    report = backfill_local_links(session_factory, batch_size=1)
    assert report['by_source']['ACM Open'] == 1
    db.refresh(sample_paper)
    assert sample_paper.oa_url == 'https://dl.acm.org/doi/10.1145/3544548.3580688'
    assert backfill_local_links(session_factory, batch_size=1)['publisher_filled'] == 0
