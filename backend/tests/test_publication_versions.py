from pathlib import Path
import pytest
from app.cleaning import normalize_title
from app.models import Paper, Author, PaperAuthor, PaperDirection
from scripts.reconcile_papers import _backup
from scripts.reconcile_publication_versions import reconcile_versions


def add_pair(db, venue, *, second_doi='10.1234/published', second_arxiv=None):
    old = Paper(source='dblp', dblp_key='conf/nips/Example24', title='A verified publication', title_norm=normalize_title('A verified publication'), venue_id=venue.id, year=2023, publication_date='2023-06-01', ccf_level='A', doi='10.48550/arxiv.2301.12345', official_url='https://arxiv.org/abs/2301.12345', note='Keep user note')
    official = Paper(source='manual', publisher_key='https://publisher.example/2024/article', title=old.title, title_norm=old.title_norm, venue_id=venue.id, year=2024, ccf_level='A', doi=second_doi, arxiv_id=second_arxiv, official_url='https://publisher.example/2024/article', note='Verified official proceedings')
    author = Author(name='Lovelace, Ada', name_norm='lovelaceada')
    db.add_all([old, official, author]); db.flush()
    db.add_all([PaperAuthor(paper_id=p.id, author_id=author.id, author_order=0) for p in (old, official)])
    db.commit()
    return old, official


def test_version_merge_preserves_old_id_arxiv_and_manual_labels(db, engine, sample_venue, sample_direction):
    old, official = add_pair(db, sample_venue)
    old_id = old.id
    db.add(PaperDirection(paper_id=official.id, direction_id=sample_direction.id, source='manual', score=7.0)); db.commit()
    report = reconcile_versions(Path(engine.url.database))
    db.expire_all()
    p = db.query(Paper).one()
    assert p.id == old_id and p.year == 2024 and p.publication_date is None
    assert p.doi == '10.1234/published' and p.arxiv_id == '2301.12345'
    assert p.publisher_key == 'https://publisher.example/2024/article'
    assert 'Keep user note' in p.note and 'Verified official proceedings' in p.note
    tag = db.query(PaperDirection).one()
    assert (tag.paper_id, tag.source, tag.score) == (old_id, 'manual', 7.0)
    assert report['counts']['merged'] == 1 and report['fts_integrity'] == 'ok'
    assert report['foreign_key_errors'] == [] and Path(report['backup']).is_file()


@pytest.mark.parametrize('conflict', ['doi', 'author', 'arxiv'])
def test_version_merge_rejects_conflicting_identity(db, engine, sample_venue, conflict):
    old, official = add_pair(db, sample_venue, second_arxiv='2402.54321' if conflict == 'arxiv' else None)
    if conflict == 'doi':
        old.doi = '10.1234/different'
    elif conflict == 'author':
        author = Author(name='Turing, Alan', name_norm='turingalan'); db.add(author); db.flush()
        db.query(PaperAuthor).filter(PaperAuthor.paper_id == official.id).delete()
        db.add(PaperAuthor(paper_id=official.id, author_id=author.id, author_order=0))
    db.commit()
    report = reconcile_versions(Path(engine.url.database))
    assert report['counts']['merged'] == 0
    db.expire_all(); assert db.query(Paper).count() == 2


def test_arxiv_link_restored_by_strong_id_from_backup(db, engine, sample_venue):
    p = Paper(source='openalex', openalex_id='W100', title='Published paper', title_norm='published paper', venue_id=sample_venue.id, year=2024, ccf_level='A', doi='10.48550/arxiv.2301.12345', official_url='https://arxiv.org/abs/2301.12345')
    db.add(p); db.commit(); path = Path(engine.url.database)
    before = _backup(path)
    p.doi = '10.1234/formal'; db.commit()
    report = reconcile_versions(path, before)
    db.expire_all(); assert db.query(Paper).one().arxiv_id == '2301.12345'
    assert report['counts']['arxiv_restored'] == 1


def test_version_merge_accepts_anchored_initials_and_existing_arxiv_owner(db, engine, sample_venue):
    old, official = add_pair(db, sample_venue, second_arxiv='2301.12345')
    abbreviated = Author(name='Turing, A.', name_norm='turinga')
    full = Author(name='Turing, Alan', name_norm='turingalan')
    db.add_all([abbreviated, full]); db.flush()
    db.add_all([
        PaperAuthor(paper_id=old.id, author_id=abbreviated.id, author_order=1),
        PaperAuthor(paper_id=official.id, author_id=full.id, author_order=1),
    ]); db.commit()
    old_id = old.id
    report = reconcile_versions(Path(engine.url.database))
    db.expire_all()
    assert report['counts']['merged'] == 1
    paper = db.query(Paper).one()
    assert paper.id == old_id and paper.year == 2024 and paper.arxiv_id == '2301.12345'
    names = [name for name, in db.query(Author.name).join(PaperAuthor).filter(PaperAuthor.paper_id == paper.id)]
    assert sorted(names) == ['Lovelace, Ada', 'Turing, Alan']


def test_version_merge_does_not_claim_third_publications_arxiv_identity(db, engine, sample_venue):
    old, official = add_pair(db, sample_venue)
    unrelated = Paper(source='manual', doi='10.1234/unrelated', arxiv_id='2301.12345',
                      title='A distinct journal extension', title_norm='a distinct journal extension',
                      venue_id=sample_venue.id, year=2025, ccf_level='A',
                      official_url='https://doi.org/10.1234/unrelated')
    db.add(unrelated); db.commit()
    report = reconcile_versions(Path(engine.url.database))
    db.expire_all()
    assert report['counts']['merged'] == 1
    assert db.query(Paper).count() == 2
    merged = db.get(Paper, old.id)
    assert merged.arxiv_id is None and merged.oa_url == 'https://arxiv.org/abs/2301.12345'
    assert db.get(Paper, unrelated.id).arxiv_id == '2301.12345'


def test_version_reconcile_dry_run_leaves_source_unchanged(db, engine, sample_venue):
    old, official = add_pair(db, sample_venue)
    path = Path(engine.url.database)
    report = reconcile_versions(path, dry_run=True)
    db.expire_all()
    assert report['counts']['merged'] == 1 and report['dry_run'] is True
    assert db.query(Paper).count() == 2
    assert db.get(Paper, old.id).year == 2023


def test_catalogue_anchor_merges_crossref_verified_duplicate(db, engine, sample_venue):
    old, official = add_pair(db, sample_venue)
    official.doi = None
    db.flush()
    old.doi = "10.1234/published"
    old.year = official.year
    old.note = "Verified publisher metadata: Crossref DOI 10.1234/published"
    db.commit()
    report = reconcile_versions(Path(engine.url.database))
    db.expire_all()
    assert report["counts"]["merged"] == 1
    paper = db.query(Paper).one()
    assert paper.doi == "10.1234/published"
    assert paper.publisher_key == "https://publisher.example/2024/article"
