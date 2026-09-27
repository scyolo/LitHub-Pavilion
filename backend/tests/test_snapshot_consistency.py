"""Published metadata must agree with one consistent public database view."""
import json

import pytest

from app.models import Direction, Paper, PaperDirection
from app.services.snapshot import export_snapshot


def test_current_snapshot_matches_every_public_record(session_factory, api_catalog, tmp_path):
    from app.services.snapshot import snapshot_matches_database

    manifest = export_snapshot(session_factory, tmp_path, chunk_size=2)
    assert snapshot_matches_database(session_factory, tmp_path, manifest)


@pytest.mark.parametrize("field,value", [
    ("title", "A corrected title"), ("abstract", "Updated complete abstract"),
    ("oa_url", "https://example.org/new-paper"), ("year", 2025),
])
def test_same_count_changed_metadata_is_not_current(session_factory, sample_paper, db, tmp_path, field, value):
    from app.services.snapshot import snapshot_matches_database

    manifest = export_snapshot(session_factory, tmp_path)
    setattr(sample_paper, field, value)
    db.commit()
    assert not snapshot_matches_database(session_factory, tmp_path, manifest)
    updated = export_snapshot(session_factory, tmp_path)
    assert snapshot_matches_database(session_factory, tmp_path, updated)
    assert updated["revision"] != manifest["revision"]


def test_changed_direction_links_are_detected_without_paper_updates(session_factory, sample_paper, sample_direction, db, tmp_path):
    from app.services.snapshot import snapshot_matches_database

    manifest = export_snapshot(session_factory, tmp_path)
    before = sample_paper.updated_at
    db.add(PaperDirection(paper_id=sample_paper.id, direction_id=sample_direction.id, source="manual", score=1))
    db.commit()
    assert sample_paper.updated_at == before
    assert not snapshot_matches_database(session_factory, tmp_path, manifest)


def test_catalog_edit_and_equal_count_replacement_are_detected(session_factory, sample_paper, sample_direction, sample_venue, db, tmp_path):
    from app.services.snapshot import snapshot_matches_database

    manifest = export_snapshot(session_factory, tmp_path)
    direction = db.get(Direction, sample_direction.id)
    direction.name = "Local corrected label"
    db.commit()
    assert not snapshot_matches_database(session_factory, tmp_path, manifest)
    manifest = export_snapshot(session_factory, tmp_path)
    old_id = sample_paper.id
    db.delete(sample_paper)
    db.add(Paper(id=old_id + 100, source="manual", title="Replacement paper", title_norm="replacement paper",
                 venue_id=sample_venue.id, year=2026, ccf_level="A", doi="10.5555/replacement",
                 official_url="https://doi.org/10.5555/replacement"))
    db.commit()
    assert not snapshot_matches_database(session_factory, tmp_path, manifest)


def test_replaced_manifest_cannot_be_confirmed_as_current(session_factory, sample_paper, db, tmp_path):
    from app.services.snapshot import snapshot_matches_database

    first = export_snapshot(session_factory, tmp_path)
    sample_paper.title = "Next revision"
    db.commit()
    second = export_snapshot(session_factory, tmp_path)
    assert first["revision"] != second["revision"]
    assert not snapshot_matches_database(session_factory, tmp_path, first)
    assert snapshot_matches_database(session_factory, tmp_path, second)


def test_corrupt_snapshot_is_never_treated_as_matching_database(session_factory, sample_paper, tmp_path):
    from app.services.snapshot import snapshot_matches_database

    manifest = export_snapshot(session_factory, tmp_path)
    (tmp_path / manifest["chunks"][0]["path"]).write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(ValueError):
        snapshot_matches_database(session_factory, tmp_path, manifest)
