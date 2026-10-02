from app.collectors.dblp import RawPaper
from app.models import Paper
from app.services.publisher_import import apply_records


def incoming(doi='10.5555/same-name'):
    url = 'https://doi.org/' + doi
    return RawPaper(source='manual', venue_key=url, title='Verified Study', year=2024,
                    authors=['Wei, Wenda', 'Wei, Wen-Da'], doi=doi, official_url=url,
                    extra={'publisher_key': url})


def test_same_normalized_authors_are_not_silently_dropped(db, sample_venue):
    result = apply_records(db, [incoming()], sample_venue)
    assert result['counts'].get('new', 0) == 0
    assert result['counts']['identity_conflicts'] == 1
    assert result['conflicts'][0]['reason'] == 'author_multiplicity_not_representable'
    assert db.query(Paper).count() == 0


def test_guard_preserves_existing_candidate_state(db, sample_paper):
    sample_paper.venue_confirmed = 0
    db.commit()
    before = (sample_paper.title, sample_paper.publisher_key, sample_paper.venue_confirmed)
    result = apply_records(db, [incoming(sample_paper.doi)], sample_paper.venue)
    db.refresh(sample_paper)
    assert result['counts']['identity_conflicts'] == 1
    assert (sample_paper.title, sample_paper.publisher_key, sample_paper.venue_confirmed) == before
