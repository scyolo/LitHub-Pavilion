"""Regression coverage for UI-only metadata normalization and new topic labels."""
import pytest

from app.api.serializers import abstract_text


@pytest.mark.parametrize("raw", [None, "", "   ", ",", "...", "\n，。！？\t"])
def test_placeholder_abstracts_are_absent_everywhere(client, db, sample_paper, raw):
    sample_paper.abstract = raw
    db.commit()
    assert client.get("/api/stats/dashboard").json()["with_abstract"] == 0
    assert client.get("/api/papers").json()["items"][0]["abstract_preview"] is None
    assert client.get(f"/api/papers/{sample_paper.id}").json()["abstract"] is None
    db.refresh(sample_paper)
    assert sample_paper.abstract == raw


def test_real_abstract_is_preserved():
    assert abstract_text("  We present an efficient decoder.  ") == "We present an efficient decoder."
    assert abstract_text("提出一种图像分割方法。") == "提出一种图像分割方法。"


def test_adjacent_topics_extend_without_replacing_existing_labels(db, sample_paper, sample_direction):
    from app.models import Direction, PaperDirection
    from scripts.extend_topics import extend_topics

    sample_paper.title = "Multimodal Reinforcement Learning with Vision-Language Models"
    sample_paper.abstract = "We study reinforcement learning and multimodal reasoning."
    db.add(PaperDirection(paper_id=sample_paper.id, direction_id=sample_direction.id, score=0, source="manual"))
    db.commit()
    result = extend_topics(db)
    assert result["added_labels"]["multimodal"] == 1
    assert result["added_labels"]["rl"] == 1
    manual = db.get(PaperDirection, (sample_paper.id, sample_direction.id))
    assert manual.source == "manual"
    second = extend_topics(db)
    assert sum(second["added_labels"].values()) == 0
    assert db.query(Direction).count() == 7
