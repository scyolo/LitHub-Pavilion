from types import SimpleNamespace

from scripts.audit_coverage_ledger import compare_unit


def raw(paper):
    return SimpleNamespace(doi=paper.doi, title=paper.title, authors=['Ada Lovelace'])


def test_ledger_checks_real_admission_and_authors_not_just_import_count(db, sample_paper):
    from app.models import Author, PaperAuthor
    author = Author(name='Ada Lovelace', name_norm='adalovelace')
    db.add(author); db.flush()
    db.add(PaperAuthor(paper_id=sample_paper.id, author_id=author.id, author_order=1)); db.commit()
    result = compare_unit(db, sample_paper.venue, 2024, [raw(sample_paper)], [])
    assert result['official_scope_identity_complete']
    assert result['public_identity_matches'] == 1
    assert result['full_venue_year_coverage_verified'] is False
    sample_paper.venue_confirmed = 0; db.commit()
    result = compare_unit(db, sample_paper.venue, 2024, [raw(sample_paper)], [])
    assert not result['official_scope_identity_complete']
    assert result['missing_or_conflicting'][0]['reason'] == 'not_publicly_admitted'


def test_unresolved_official_item_prevents_scope_complete(db, sample_paper):
    result = compare_unit(db, sample_paper.venue, 2024, [], [{'title': 'Unknown', 'reason': 'identity_unresolved'}])
    assert result['official_count'] == 1
    assert not result['official_scope_identity_complete']


def test_different_authors_cannot_pass_coverage_gate(db, sample_paper):
    result = compare_unit(db, sample_paper.venue, 2024, [raw(sample_paper)], [])
    assert result['public_identity_matches'] == 0
    assert result['missing_or_conflicting'][0]['reason'] == 'author_identity_mismatch'


def test_punctuation_equivalent_names_pass_but_duplicate_author_count_does_not(db, sample_paper):
    from app.models import Author, PaperAuthor
    a = Author(name='Wei, Wen-Da', name_norm='weiwenda'); db.add(a); db.flush()
    db.add(PaperAuthor(paper_id=sample_paper.id, author_id=a.id, author_order=1)); db.commit()
    record = raw(sample_paper); record.authors = ['Wei, Wenda']
    assert compare_unit(db, sample_paper.venue, 2024, [record], [])['public_identity_matches'] == 1
    record.authors *= 2
    assert compare_unit(db, sample_paper.venue, 2024, [record], [])['public_identity_matches'] == 0


def test_ledger_database_is_read_only_and_unchecked_sources_not_declared_complete(engine, sample_paper, tmp_path):
    from pathlib import Path
    from scripts.audit_coverage_ledger import build_ledger
    path = Path(engine.url.database)
    before = path.read_bytes()
    result = build_ledger(path, tmp_path, [2024])
    assert result['read_only'] and result['network_requests'] == 0
    assert result['configured_sources'] == result['source_year_units'] == 1
    assert result['units'][0]['public_records'] == 1
    assert result['units'][0]['selected_research_scope'] is None
    assert not result['full_coverage_verified']
    assert path.read_bytes() == before
