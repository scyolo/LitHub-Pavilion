import pytest

from app.models import Paper, Venue
from scripts.reconcile_catalog_levels import reconcile_levels


def catalog(venue):
    seed = {field: getattr(venue, field) for field in ("abbr", "name", "type", "dblp_stream")}
    seed["ccf_level"] = "B"
    proof = {"venues": {venue.abbr: {"level": "B", "type": venue.type,
                                   "dblp_stream": venue.dblp_stream, "pages": [42]}}}
    return {venue.abbr: seed}, proof


def test_grade_reconciliation_is_explicit_atomic_and_preserves_identities(db, sample_paper):
    paper = sample_paper
    venue = db.get(Venue, paper.venue_id)
    paper.note = "Preserve my reading notes"
    db.commit()
    seeds, proof = catalog(venue)
    old = {field: getattr(paper, field) for field in ("id", "title", "doi", "year", "note", "venue_id")}
    plan = reconcile_levels(db, seeds, proof, [venue.abbr])
    assert plan[0]["paper_ids"] == [paper.id]
    assert venue.ccf_level == paper.ccf_level == "A"
    reconcile_levels(db, seeds, proof, [venue.abbr], apply=True)
    db.commit()
    assert venue.ccf_level == paper.ccf_level == "B"
    assert {field: getattr(paper, field) for field in old} == old
    assert db.query(Paper).count() == 1
    assert reconcile_levels(db, seeds, proof, [venue.abbr], apply=True) == []


@pytest.mark.parametrize("field,value", [("name", "Another conference"), ("dblp_stream", "conf/another"), ("ccf_level", "A")])
def test_catalog_mismatch_does_not_rewrite_local_source(db, sample_paper, field, value):
    venue = db.get(Venue, sample_paper.venue_id)
    seeds, proof = catalog(venue)
    seeds[venue.abbr][field] = value
    with pytest.raises(ValueError):
        reconcile_levels(db, seeds, proof, [venue.abbr], apply=True)
    assert venue.ccf_level == sample_paper.ccf_level == "A"
