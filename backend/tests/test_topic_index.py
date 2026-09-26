from pathlib import Path

from app.models import Direction, DirectionRule, PaperDirection


SEEDS = Path(__file__).resolve().parents[2] / "seeds"


def test_reindex_preserves_manual_tags_settings_and_paper_metadata(db, sample_paper, sample_direction):
    from app.services.topic_index import reindex_topics
    llm = Direction(code="llm", name="Customized name", min_score=2, enabled=1)
    disabled = Direction(code="cv", name="Disabled vision", min_score=4, enabled=0)
    db.add_all([llm, disabled])
    db.flush()
    manual = PaperDirection(paper_id=sample_paper.id, direction_id=sample_direction.id, source="manual", score=9)
    db.add(manual)
    sample_paper.title = "ChatGPT for Image Restoration"
    sample_paper.note = "Private unchanged"
    db.commit()
    original = {column.name: getattr(sample_paper, column.name) for column in sample_paper.__table__.columns}
    first = reindex_topics(db, SEEDS)
    assert first["added_labels"]["llm"] == 1
    assert first["after"]["cv"] == 0
    assert db.get(Direction, llm.id).name == "Customized name"
    assert db.get(Direction, disabled.id).min_score == 4
    assert db.get(PaperDirection, (sample_paper.id, sample_direction.id)).source == "manual"
    assert db.get(PaperDirection, (sample_paper.id, sample_direction.id)).score == 9
    db.refresh(sample_paper)
    assert {column.name: getattr(sample_paper, column.name) for column in sample_paper.__table__.columns} == original
    second = reindex_topics(db, SEEDS)
    assert sum(second["added_labels"].values()) == 0
    assert sum(second["removed_labels"].values()) == 0
    assert second["rules_added"] == 0


def test_only_unmodified_legacy_rule_is_refined(db, sample_paper):
    from app.services.topic_index import reindex_topics
    direction = Direction(code="multimodal", name="Multimodal", min_score=2, enabled=1)
    db.add(direction)
    db.flush()
    rule = DirectionRule(direction_id=direction.id, keyword=r"\bmulti[- ]?modal\b", weight=1, field="both", enabled=1)
    db.add(rule)
    db.add(PaperDirection(paper_id=sample_paper.id, direction_id=direction.id, score=2, source="rule"))
    sample_paper.title = "Multimodal optimization of functions"
    sample_paper.abstract = None
    db.commit()
    result = reindex_topics(db, SEEDS)
    assert result["rules_refined"] == 1
    assert result["removed_labels"]["multimodal"] == 1
    assert db.get(PaperDirection, (sample_paper.id, direction.id)) is None


def test_disabled_legacy_rule_does_not_become_enabled_through_replacement(db, sample_paper):
    from app.services.topic_index import reindex_topics
    direction = Direction(code="multimodal", name="Multimodal", min_score=2, enabled=1)
    db.add(direction)
    db.flush()
    old = DirectionRule(direction_id=direction.id, keyword=r"\bmulti[- ]?modal\b", weight=1, field="both", enabled=0)
    db.add(old)
    db.commit()
    reindex_topics(db, SEEDS)
    db.refresh(old)
    assert old.enabled == 0
    assert len(db.query(DirectionRule).filter(DirectionRule.direction_id == direction.id, DirectionRule.keyword.like("%multi[- ]?modal%")).all()) == 1
