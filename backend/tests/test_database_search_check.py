from pathlib import Path

import pytest

from scripts.check_database_search import check_search


def test_real_search_check_does_not_modify_database(engine, sample_paper):
    path = Path(engine.url.database)
    before = path.read_bytes()
    result = check_search(path,[{'id':sample_paper.id,'title':sample_paper.title,
                                 'venue':sample_paper.venue.abbr,'year':sample_paper.year}],expected_count=1)
    assert result['read_only'] and result['query_only']
    assert result['exact_title_checks'] == 1 and result['network_requests'] == 0
    assert result['all_title_identity_checks'] == 1 and result['all_titles_queryable']
    assert not result['api_lifespan_started']
    assert path.read_bytes() == before


def test_real_search_check_rejects_stale_snapshot_count(engine,sample_paper):
    with pytest.raises(ValueError,match='stale'):
        check_search(Path(engine.url.database),[{'id':sample_paper.id,'title':sample_paper.title}],expected_count=2)


def test_real_search_check_detects_missing_identity(engine,sample_paper):
    with pytest.raises(AssertionError,match='Expected identity missing'):
        check_search(Path(engine.url.database),[{'id':999,'title':sample_paper.title}])


def test_real_search_check_uses_public_admission_not_private_candidate_count(engine, sample_paper, db):
    from app.models import Paper
    db.add(Paper(source='manual', title='Unverified Candidate', title_norm='unverified candidate',
                 venue_id=sample_paper.venue_id, year=2024, ccf_level='A', venue_confirmed=0,
                 official_url='https://arxiv.org/abs/2501.12345', arxiv_id='2501.12345'))
    db.commit()
    path = Path(engine.url.database)
    before = path.read_bytes()
    result = check_search(path, [{'id': sample_paper.id, 'title': sample_paper.title,
                                 'venue': sample_paper.venue.abbr, 'year': sample_paper.year}], expected_count=1)
    assert result['paper_count'] == result['all_title_identity_checks'] == 1
    assert result['stored_record_count'] == 2
    assert path.read_bytes() == before
