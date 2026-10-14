"""Cross-layer regression tests for evidence-based open full-text coverage."""
import pytest

from app.api.serializers import paper_links


def test_publisher_evidence_is_shared_by_cards_stats_filters_and_snapshot(client, db, session_factory, sample_paper, tmp_path):
    from app.services.snapshot import export_snapshot
    import json

    sample_paper.publisher_key = 'https://proceedings.mlr.press/v267/fu25f.html'
    db.commit()
    expected = sample_paper.publisher_key
    assert paper_links(sample_paper)['oa_url'] == expected
    assert client.get('/api/stats/dashboard').json()['with_oa_link'] == 1
    assert client.get('/api/papers', params={'access': 'oa'}).json()['total'] == 1
    assert client.get('/api/papers', params={'access': 'official'}).json()['total'] == 0
    manifest = export_snapshot(session_factory, tmp_path / 'snapshot')
    catalog = json.loads((tmp_path / 'snapshot' / manifest['catalog']['path']).read_text(encoding='utf-8'))
    for scope in catalog['overview']['scopes']:
        counts = scope['dashboard']
        assert counts['with_oa_link'] == counts['total']
    rows = json.loads((tmp_path / 'snapshot' / manifest['chunks'][0]['path']).read_text(encoding='utf-8'))
    assert rows[0]['oa_url'] == expected
    db.refresh(sample_paper)
    assert sample_paper.oa_url is None  # Reading never mutates stored metadata.


def test_ingestion_recognizes_open_publisher_link_even_when_doi_is_official(db, sample_venue):
    from app.collectors.dblp import RawPaper
    from app.services.paper_store import upsert_paper

    raw = RawPaper(source='dblp', venue_key='conf/nips/open24', title='Open Publisher Evidence',
                   year=2024, authors=['Test Author'], doi='10.5555/open.24',
                   official_url='https://proceedings.mlr.press/v235/open24a.html')
    paper, created = upsert_paper(db, raw, sample_venue)
    assert created
    assert paper.oa_url == raw.official_url
    assert paper.official_url == 'https://doi.org/10.5555/open.24'


@pytest.mark.parametrize('official', ['https://ieeexplore.ieee.org/document/1234',
                                     'https://openreview.net/group?id=ICLR.cc/2025/Conference'])
def test_unverified_official_pages_remain_outside_oa_statistics(client, db, sample_paper, official):
    sample_paper.publisher_key = official
    db.commit()
    assert paper_links(sample_paper)['oa_url'] is None
    assert client.get('/api/stats/dashboard').json()['with_oa_link'] == 0


@pytest.mark.asyncio
async def test_local_only_scan_does_not_construct_a_network_client(db, session_factory, sample_paper, monkeypatch):
    from app.services import links_backfill
    sample_paper.publisher_key = 'https://openreview.net/forum?id=WCVMqRHWW5'
    db.commit()
    def no_network():
        raise AssertionError('Local maintenance must not access the network')
    monkeypatch.setattr(links_backfill, 'make_client', no_network)
    result = await links_backfill.run_links_backfill(session_factory, local_only=True)
    assert result['publisher_filled'] == 1
    assert result['openalex_filled'] == result['checked'] == 0
    db.refresh(sample_paper)
    assert sample_paper.oa_url == sample_paper.publisher_key


@pytest.mark.asyncio
async def test_invalid_budget_is_rejected_before_any_database_write(db, session_factory, sample_paper):
    from app.services.links_backfill import run_links_backfill
    sample_paper.publisher_key = 'https://proceedings.mlr.press/v267/fu25f.html'
    sample_paper.pdf_status = 'pending'
    db.commit()
    with pytest.raises(ValueError, match='max_batches'):
        await run_links_backfill(session_factory, max_batches=-1)
    db.refresh(sample_paper)
    assert sample_paper.oa_url is None
    assert sample_paper.pdf_status == 'pending'
