from types import SimpleNamespace
from scripts.report_actual_gaps import classify_verified


def test_only_confirmed_empty_identity_lookup_counts_as_absence(sample_paper):
    raw = SimpleNamespace(doi=sample_paper.doi,title=sample_paper.title,year=sample_paper.year)
    row = {column.name:getattr(sample_paper,column.name) for column in sample_paper.__table__.columns}
    venue=sample_paper.venue
    assert classify_verified(raw, [], venue)=='verified_identity_absent_from_database'
    assert classify_verified(raw, [row], venue)=='existing_publication'
    assert classify_verified(raw, [dict(row,venue_confirmed=0)],venue)=='existing_not_publicly_admitted'
    assert classify_verified(raw, [dict(row,title_norm='changed')],venue)=='existing_metadata_difference'
    assert classify_verified(raw,[row,row],venue)=='existing_identity_conflict'
