import pytest

from app.api.filtering import PaperFilters, paper_query
from app.models import Paper, PaperConference, PaperDirection, Venue


@pytest.fixture
def linked_publication(db, sample_paper, sample_venue, sample_direction):
    sample_venue.abbr = 'JVIS'
    sample_venue.name = 'Journal of Visualization'
    sample_venue.type = 'journal'
    conference = Venue(abbr='VIS', name='Visualization Conference', type='conf', ccf_level='A')
    db.add(conference)
    db.flush()
    db.add_all([
        PaperConference(paper_id=sample_paper.id, venue_id=conference.id, event_year=year,
                        evidence_url='https://example.org/vis/program', evidence_sha256='a' * 64)
        for year in (2025, 2026)
    ])
    db.add(PaperDirection(paper_id=sample_paper.id, direction_id=sample_direction.id,
                          source='manual', score=7))
    sample_paper.note = 'Reader note'
    db.commit()
    return sample_paper, conference


def test_opted_in_source_scope_keeps_one_canonical_paper_and_publication_year(db, linked_publication):
    paper, _ = linked_publication
    assert paper_query(db, PaperFilters(venue='VIS')).count() == 0
    selected = PaperFilters(venue='VIS', type='conf', level='A', year=2024, include_associated=True)
    result = paper_query(db, selected).all()
    assert [p.id for p in result] == [paper.id]
    assert result[0].venue.abbr == 'JVIS' and result[0].year == 2024
    assert paper_query(db, PaperFilters(venue='VIS', year=2025, include_associated=True)).count() == 0
    assert paper_query(db, PaperFilters(venue='VIS', type='journal', include_associated=True)).count() == 0
    assert paper_query(db, PaperFilters(venue='VIS', level='B', include_associated=True)).count() == 0
    assert paper_query(db, PaperFilters()).count() == db.query(Paper).count() == 1
    assert paper.note == 'Reader note'


def test_associations_do_not_promote_unconfirmed_candidates(db, linked_publication):
    from app.services.conference_scope import public_conference_associations

    paper, _ = linked_publication
    paper.venue_confirmed = 0
    db.commit()
    assert paper_query(db, PaperFilters(venue='VIS', include_associated=True)).count() == 0
    assert public_conference_associations(db) == {}
    assert db.query(Paper).count() == 1


def test_api_search_lists_linked_journal_papers_without_duplicate_year_associations(client, db, linked_publication, sample_direction):
    paper, _ = linked_publication
    params = {'venue': 'VIS', 'type': 'conf', 'level': 'A', 'year': 2024,
              'include_associated': 'true', 'direction': sample_direction.code}
    for route in ['/api/papers', '/api/search']:
        extra = {'q': paper.title, 'match': 'exact'} if route.endswith('search') else {}
        response = client.get(route, params=params | extra)
        assert response.status_code == 200
        assert response.json()['total'] == 1
        assert response.json()['items'][0]['venue'] == 'JVIS'
    counts = client.get('/api/stats/dashboard', params={'type': 'conf'}).json()
    assert counts['total'] == 0
    assert next(v for v in counts['venues'] if v['abbr'] == 'VIS')['associated_paper_count'] == 1
    topics = client.get('/api/stats/venue-topics', params=params)
    assert topics.status_code == 200
    assert topics.json()['items']['VIS'] == [{'code': sample_direction.code, 'paper_count': 1}]


def test_snapshot_carries_only_public_association_ids_and_tracks_relation_changes(db, linked_publication, session_factory, tmp_path):
    from app.services.snapshot import _load_entry, export_snapshot, snapshot_matches_database

    paper, conference = linked_publication
    manifest = export_snapshot(session_factory, tmp_path)
    catalog, _ = _load_entry(tmp_path, manifest['catalog'], 'catalog')
    assert catalog['conference_associations'] == {'VIS': {'2025': [paper.id], '2026': [paper.id]}}
    assert snapshot_matches_database(session_factory, tmp_path, manifest)
    db.query(PaperConference).filter_by(venue_id=conference.id, event_year=2026).delete()
    db.commit()
    assert not snapshot_matches_database(session_factory, tmp_path, manifest)
