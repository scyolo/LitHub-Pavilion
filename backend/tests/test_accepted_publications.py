import pytest

from app.api.filtering import PaperFilters, paper_query
from app.cleaning import normalize_title
from app.services import accepted_publications as accepted


@pytest.fixture
def acceptance(monkeypatch, sample_venue):
    record = {
        'reference_id': 'accepted-example-2026', 'title': 'Accepted LLM Serving Method',
        'authors': ['Lee, Ada'], 'venue': sample_venue.abbr, 'year': 2026, 'level': 'A',
        'status': 'accepted_publication_unverified', 'official_url': 'https://example.org/accepted',
        'preprint_url': None, 'aliases': ['ExampleMethod'], 'directions': ['inference'],
        'evidence_sha256': 'a' * 64, 'verified_on': '2026-10-19',
    }
    monkeypatch.setattr(accepted, 'REFERENCE_ROWS', [record])
    return record


def test_acceptance_is_searchable_separately_without_inflating_published_counts(client, db, acceptance):
    result = client.get('/api/search', params={'q': acceptance['title'], 'match': 'exact'}).json()
    assert result['total'] == 0 and result['items'] == []
    assert result['accepted_items'] == [acceptance]
    assert paper_query(db, PaperFilters()).count() == 0
    assert client.get('/api/stats/dashboard').json()['total'] == 0
    wrong = client.get('/api/search', params={'q': acceptance['title'], 'year': 2025}).json()
    assert 'accepted_items' not in wrong
    assert 'accepted_items' not in client.get('/api/search', params={'q': 'unrelated research'}).json()


def test_formal_publication_supersedes_acceptance_reference(db, sample_paper, acceptance):
    sample_paper.title = acceptance['title']
    sample_paper.title_norm = normalize_title(acceptance['title'])
    sample_paper.year = acceptance['year']
    db.commit()
    assert accepted.accepted_references(db) == []
    sample_paper.venue_confirmed = 0
    db.commit()
    assert accepted.accepted_references(db) == [acceptance]


def test_acceptance_filters_do_not_relax_year_type_level_or_direction(acceptance):
    assert accepted.match_accepted_references([acceptance], 'ExampleMethod', PaperFilters()) == [acceptance]
    assert not accepted.match_accepted_references([acceptance], '无关中文查询', PaperFilters(venue=acceptance['venue']))
    assert accepted.match_accepted_references([acceptance], '', PaperFilters(venue=acceptance['venue'])) == [acceptance]
    for filters in [PaperFilters(type='journal'), PaperFilters(level='B'), PaperFilters(year=2025),
                    PaperFilters(venue='OTHER'), PaperFilters(directions=('cv',)), PaperFilters(access='oa')]:
        assert not accepted.match_accepted_references([acceptance], 'ExampleMethod', filters)


def test_scoped_chinese_topic_is_not_mistaken_for_an_empty_exact_title(client, db, acceptance):
    from app.models import Direction

    db.add(Direction(code='inference', name='推理优化', enabled=1))
    db.commit()
    result = client.get('/api/search', params={'q': '推理优化', 'venue': acceptance['venue']}).json()
    assert result['match_mode'] == 'topic'
    assert result['accepted_items'] == [acceptance]


def test_acceptance_cannot_claim_to_be_a_published_record(acceptance):
    venues = {acceptance['venue']: {'type': 'conf', 'level': 'A'}}
    accepted.validate_accepted_references([acceptance], venues)
    with pytest.raises(ValueError):
        accepted.validate_accepted_references([acceptance | {'status': 'published'}], venues)
    with pytest.raises(ValueError):
        accepted.validate_accepted_references([acceptance | {'official_url': 'javascript:alert(1)'}], venues)
