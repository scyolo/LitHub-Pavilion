import json

from app.models import PaperConference, Venue
from app.services.snapshot import export_snapshot
from scripts.export_source_audit import export_audit


def test_export_links_shared_papers_without_inflating_snapshot_total(
    db, session_factory, sample_paper, tmp_path
):
    conference = Venue(
        abbr="Shared", name="Shared Conference", type="conf", ccf_level="A", active=1
    )
    db.add(conference)
    db.flush()
    db.add(
        PaperConference(
            paper_id=sample_paper.id,
            venue_id=conference.id,
            event_year=2024,
            evidence_url="https://publisher.example/toc",
            evidence_sha256="a" * 64,
        )
    )
    db.commit()
    snapshot = tmp_path / "snapshot"
    manifest = export_snapshot(session_factory, snapshot)
    target = tmp_path / "data-sources"
    index = export_audit(db, snapshot, target)
    assert index["snapshot_papers"] == 1 and index["represented_sources"] == 2
    assert (
        index["full_coverage_verified"] is False
        and index["snapshot_revision"] == manifest["revision"]
    )
    row = next(s for s in index["sources"] if s["abbr"] == "Shared")
    assert row["primary_count"] == 0 and row["associated_count"] == 1
    linked = json.loads(
        (target / row["associations"]["path"]).read_text(encoding="utf-8")
    )
    assert linked["papers"][0]["id"] == sample_paper.id
    assert linked["papers"][0]["canonical_venue"] == "NeurIPS"
    assert db.query(Venue).count() == 2


def test_legacy_papers_are_preserved_but_not_counted_in_2023_2026_coverage(
    db, session_factory, sample_paper, tmp_path
):
    sample_paper.year = 2021
    db.commit()
    snapshot = tmp_path / "snapshot"
    export_snapshot(session_factory, snapshot)
    result = export_audit(db, snapshot, tmp_path / "output")
    assert result["snapshot_papers"] == 1
    assert result["sources"][0]["primary_count"] == 0
    assert result["sources"][0]["primary_years"] == {}
