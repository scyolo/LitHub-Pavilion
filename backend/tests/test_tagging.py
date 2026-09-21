"""打标规则引擎测试：打分公式、阈值、manual 保留（A9）。"""

from app.services.tagging import apply_tagging, score_text


def _rules():
    # (direction_id, regex, weight, field)
    return [
        (1, r"speculative (decoding|sampling|inference)", 1.0, "both"),
        (2, r"\bagents?\b", 0.5, "both"),  # 泛词低权重
        (3, r"large language models?", 1.0, "both"),
    ]


def test_title_hit_scores_double():
    scores = score_text(_rules(), "Fast Inference via Speculative Decoding", None)
    assert scores[1] == 2.0  # title 命中 ×2


def test_generic_agent_word_needs_cooccurrence():
    # 单次泛词命中 0.5×2=1.0 < 阈值 2 → 分数不足以入选
    scores = score_text(_rules(), "A Study of User Agent Behavior", None)
    assert scores.get(2, 0.0) < 2.0
    # 共现（multi-agent / autonomous agents / agents）+ 标题命中 → ≥2 入选
    scores = score_text(
        _rules(),
        "Agents that plan",
        "multi-agent systems and autonomous agents with agents",
    )
    assert scores[2] >= 2.0


def test_abstract_hit_scores_single():
    scores = score_text(_rules(), "An Efficient Framework", "We use speculative sampling")
    assert scores[1] == 1.0


def test_manual_tags_preserved(db, sample_paper, sample_direction, session_factory):
    from app.models import Direction, PaperDirection

    llm = Direction(code="llm", name="大语言模型", min_score=2.0, enabled=1)
    db.add(llm)
    db.commit()
    # 人工标注 llm + 规则自动命中 specdec
    db.add(PaperDirection(paper_id=sample_paper.id, direction_id=llm.id, score=0, source="manual"))
    db.commit()
    final = apply_tagging(db, sample_paper.id, sample_paper.title, sample_paper.abstract, _rules(), {1: 2.0, 2: 2.0, 3: 2.0})
    assert 1 in final          # 规则命中 specdec
    assert llm.id in final     # manual 标签保留
    sources = {
        row[0]: row[1]
        for row in db.query(PaperDirection.direction_id, PaperDirection.source)
        .filter(PaperDirection.paper_id == sample_paper.id)
        .all()
    }
    assert sources[1] == "rule"
    assert sources[llm.id] == "manual"


def test_upsert_idempotent_by_dblp_key(db, sample_venue, sample_direction):
    """重跑同一单元 total 不变（F-003 验收口径的最小复现）。"""
    from app.collectors.dblp import RawPaper
    from app.models import Paper
    from app.services.pipeline import upsert_paper

    def _raw():
        return RawPaper(
            source="dblp",
            venue_key="conf/nips/dupe2024",
            title="A Duplicate Paper about Agents",
            year=2024,
            authors=["Adam Zhao"],
            doi="10.5555/dupe.001",
        )

    paper1, created1 = upsert_paper(db, _raw(), sample_venue)
    db.commit()
    paper2, created2 = upsert_paper(db, _raw(), sample_venue)
    db.commit()
    assert created1 is True and created2 is False
    assert paper1.id == paper2.id
    assert db.query(Paper).filter(Paper.dblp_key == "conf/nips/dupe2024").count() == 1


def test_cross_source_doi_merge(db, sample_venue):
    """OpenAlex 记录与 DBLP 记录 DOI 相同 → 归并而非新建（4.2 规则 2）。"""
    from app.collectors.dblp import RawPaper
    from app.models import Paper
    from app.services.pipeline import upsert_paper

    dblp_raw = RawPaper(
        source="dblp", venue_key="conf/nips/merge2024", title="Merge Me", year=2024,
        authors=["Adam Zhao"], doi="10.5555/merge.001",
    )
    paper1, created1 = upsert_paper(db, dblp_raw, sample_venue)
    assert created1

    openalex_raw = RawPaper(
        source="openalex", venue_key="W9999999999", title="Merge Me", year=2024,
        authors=["Zhao, Adam"], doi="https://doi.org/10.5555/merge.001",
        extra={"cited_by_count": 7},
    )
    paper2, created2 = upsert_paper(db, openalex_raw, sample_venue)
    db.commit()
    assert created2 is False
    assert paper2.id == paper1.id
    assert paper2.openalex_id == "W9999999999"
    assert paper2.citation_count == 7
    assert db.query(Paper).filter(Paper.title_norm == "merge me").count() == 1
