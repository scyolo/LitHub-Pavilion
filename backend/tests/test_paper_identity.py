from app.collectors.dblp import RawPaper
from app.models import Paper, PaperDirection
from app.services.paper_store import upsert_paper
from scripts.reconcile_papers import _merge_one


def raw(venue, **changes):
    value = dict(source="dblp", venue_key=venue.dblp_stream + "/Other24", title="Fast Inference via Speculative Decoding", year=2024, doi="10.5555/other.002", authors=[])
    value.update(changes)
    return RawPaper(**value)


def test_same_title_is_not_identity_for_two_publication_dois(db, sample_venue, sample_paper):
    other, new = upsert_paper(db, raw(sample_venue), sample_venue)
    assert new and other.id != sample_paper.id
    assert sample_paper.doi == "10.5555/test.001"


def test_cross_year_date_never_overwrites_formal_year(db, sample_venue, sample_paper):
    item = raw(sample_venue, venue_key=sample_paper.dblp_key, doi=sample_paper.doi, year=2023, publication_date="2023-08-09")
    stored, new = upsert_paper(db, item, sample_venue)
    assert not new and stored.year == 2024 and stored.publication_date is None
    item.extra["provenance"] = "dblp_toc"
    stored, _ = upsert_paper(db, item, sample_venue)
    assert stored.year == 2023 and stored.publication_date == "2023-08-09"


def test_arxiv_identity_survives_publisher_doi_replacement(db, sample_venue):
    paper, _ = upsert_paper(db, raw(sample_venue, doi="10.48550/arxiv.2301.12345"), sample_venue)
    assert paper.arxiv_id == "2301.12345"
    published, new = upsert_paper(db, raw(sample_venue, doi="10.5555/published"), sample_venue)
    assert not new and published.id == paper.id
    assert published.doi == "10.5555/published" and published.arxiv_id == "2301.12345"


def test_merging_moves_unique_ids_after_delete_and_preserves_manual_tags(db, sample_paper, sample_direction):
    other = Paper(source="openalex", openalex_id="W123", doi="10.48550/arxiv.2301.12345", arxiv_id="2301.12345", title=sample_paper.title, title_norm=sample_paper.title_norm, venue_id=sample_paper.venue_id, year=sample_paper.year, ccf_level="A", official_url="https://arxiv.org/abs/2301.12345")
    db.add(other); db.flush()
    db.add(PaperDirection(paper_id=sample_paper.id, direction_id=sample_direction.id, source="rule", score=2))
    db.add(PaperDirection(paper_id=other.id, direction_id=sample_direction.id, source="manual", score=9))
    db.flush()
    _merge_one(db, sample_paper, other)
    db.commit()
    assert sample_paper.openalex_id == "W123" and sample_paper.arxiv_id == "2301.12345"
    assert sample_paper.doi == "10.5555/test.001"
    assert db.get(PaperDirection, (sample_paper.id, sample_direction.id)).source == "manual"


def test_title_fallback_also_requires_matching_full_author_sets(db, sample_venue):
    original, _ = upsert_paper(db, raw(sample_venue, doi=None, authors=['Lovelace, Ada']), sample_venue)
    item = raw(sample_venue, source='openalex', venue_key='W-new', doi=None, authors=['Turing, Alan'])
    other, new = upsert_paper(db, item, sample_venue)
    assert new and other.id != original.id
    # Missing authors are not affirmative identity evidence either.
    item.venue_key = 'W-without-authors'; item.authors = []
    third, new = upsert_paper(db, item, sample_venue)
    assert new and third.id not in (original.id, other.id)
