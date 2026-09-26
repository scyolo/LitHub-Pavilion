"""Conservative topic coverage and metadata-enrichment regression examples."""
import csv
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.models import DirectionRule, PaperDirection
from app.services.tagging import score_text


@pytest.mark.parametrize("code,title", [
    ("llm", "Evaluating ChatGPT for text understanding"),
    ("agent", "Training GUI Agents with feedback"),
    ("cv", "Efficient Image Restoration with neural networks"),
    ("cv", "Monocular Depth Estimation in the wild"),
    ("multimodal", "Audio-Visual Event Perception"),
    ("rl", "Robust Offline RL with conservative policies"),
    ("nlp", "Dialogue Summarization with evidence"),
    ("nlp", "Text Classification under distribution shifts"),
    ("retrieval", "Efficient Retrieval-Augmentation for question answering"),
    ("alignment", "Jailbreaking Large Language Models"),
    ("alignment", "Safety Evaluation of Language Models"),
    ("specdec", "Draft-Verification for Fast Language Model Decoding"),
    ("specdec", "Self-Drafting for Parallel Token Verification"),
])
def test_seed_rules_cover_specific_research_phrases(code, title):
    path = Path(__file__).resolve().parents[2] / "seeds" / "direction_rules.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rules = [(row["direction_code"], row["keyword"], float(row["weight"]), row["field"]) for row in rows if row["enabled"] == "1"]
    assert score_text(rules, title, None).get(code, 0) >= 2


@pytest.mark.parametrize("title,code", [
    ("User agent strings in web browsers", "agent"),
    ("Multimodal optimization of benchmark functions", "multimodal"),
    ("Sequence alignment for protein structures", "alignment"),
    ("Model selection in linear regression", "llm"),
])
def test_generic_or_ambiguous_words_do_not_force_topics(title, code):
    path = Path(__file__).resolve().parents[2] / "seeds" / "direction_rules.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rules = [(r["direction_code"], r["keyword"], float(r["weight"]), r["field"]) for r in csv.DictReader(stream) if r["enabled"] == "1"]
    assert score_text(rules, title, None).get(code, 0) < 2


@pytest.mark.asyncio
async def test_monthly_enrichment_retags_updated_abstracts(session_factory, db, sample_paper, sample_direction, monkeypatch):
    from app.services import pipeline
    sample_paper.title = "Fast generation"
    sample_paper.abstract = None
    db.add(DirectionRule(direction_id=sample_direction.id, keyword="speculative decoding", field="both", weight=2, enabled=1))
    db.commit()

    @asynccontextmanager
    async def no_network():
        yield object()

    async def enrich(session, rows, client):
        for row in rows:
            row.abstract = "We improve speculative decoding."
        session.commit()
        return {"failed": 0}

    monkeypatch.setattr(pipeline, "make_client", no_network)
    monkeypatch.setattr(pipeline, "enrich_papers", enrich)
    await pipeline.CrawlPipeline(session_factory)._maintenance("monthly", "test-monthly")
    db.expire_all()
    assert db.query(PaperDirection).filter_by(paper_id=sample_paper.id, direction_id=sample_direction.id).one().source == "rule"
