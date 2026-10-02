import json

from app.models import PaperDirection
from app.services.snapshot import export_snapshot, validate_snapshot


def test_precomputed_venue_topics_use_only_public_papers_and_compact_metadata(session_factory, db, sample_paper, sample_direction, tmp_path):
    db.merge(PaperDirection(paper_id=sample_paper.id, direction_id=sample_direction.id, source="manual", score=2))
    db.commit()
    manifest = export_snapshot(session_factory, tmp_path)
    catalog = json.loads((tmp_path / manifest["catalog"]["path"]).read_text(encoding="utf-8"))
    assert catalog["overview"]["venue_topics"]["NeurIPS"] == [{"code": "specdec", "paper_count": 1}]
    assert all(set(v) == {"abbr", "paper_count", "years"}
               for scope in catalog["overview"]["scopes"] for v in scope["dashboard"]["venues"])
    assert validate_snapshot(tmp_path)["paper_count"] == 1


def test_live_venue_topics_respect_grade_and_kind(client, db, sample_paper, sample_direction):
    db.merge(PaperDirection(paper_id=sample_paper.id, direction_id=sample_direction.id, source="manual", score=2))
    db.commit()
    assert client.get("/api/stats/venue-topics?level=A&type=conf").json()["items"]["NeurIPS"] == [{"code": "specdec", "paper_count": 1}]
    assert client.get("/api/stats/venue-topics?type=journal").json()["items"] == {}
