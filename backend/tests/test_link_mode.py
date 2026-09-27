"""链接维护行为测试：新记录仅存链接、历史状态自愈、OA 补全和统计。"""
from types import SimpleNamespace

import httpx
import pytest

from app.services.enrichment import set_oa_url_if_empty


@pytest.mark.parametrize("source,venue_key", [("dblp", "conf/nips/lm2025"), ("openalex", "W123")])
def test_new_paper_is_closed_with_oa_url(db, sample_venue, source, venue_key):
    """所有来源的新论文都只保存链接，不依赖下载模式配置。"""
    from app.collectors.dblp import RawPaper
    from app.services.pipeline import upsert_paper

    raw = RawPaper(
        source=source,
        venue_key=venue_key,
        title="Link Mode Paper",
        year=2025,
        authors=["Adam Zhao"],
        doi="10.1/lm.1",
        extra={"oa_pdf": "https://arxiv.org/pdf/2501.00001"},
    )
    paper, created = upsert_paper(db, raw, sample_venue)
    db.commit()
    assert created
    assert paper.pdf_status == "closed"
    assert paper.pdf_path is None
    assert paper.pdf_source is None
    assert paper.oa_url == "https://arxiv.org/pdf/2501.00001"
    assert paper.official_url == "https://doi.org/10.1/lm.1"


@pytest.mark.parametrize("previous_status", ["pending", "failed"])
def test_ingest_selfheals_pending_and_failed_rows(db, sample_venue, sample_paper, previous_status):
    """存量待下载/失败状态在元数据更新时自愈，无需切换模式。"""
    from app.collectors.dblp import RawPaper
    from app.services.pipeline import upsert_paper

    sample_paper.pdf_status = previous_status
    db.commit()
    raw = RawPaper(
        source="dblp", venue_key="conf/nips/test2024fast", title="Fast Inference via Speculative Decoding",
        year=2024, authors=["Adam Zhao"], doi="10.5555/test.001",
    )
    paper, created = upsert_paper(db, raw, sample_venue)
    db.commit()
    assert created is False
    assert paper.pdf_status == "closed"


@pytest.mark.asyncio
@pytest.mark.parametrize("source_url,expected", [
    (" HTTPS://Repository.Example.org/paper.pdf ", "https://repository.example.org/paper.pdf"),
    ("javascript:alert(1)", None),
    ("http://127.0.0.1/private.pdf", None),
    ("https://user:password@repository.example.org/paper.pdf", None),
])
async def test_link_maintenance_needs_only_current_settings_and_sanitizes_sources(
    db, session_factory, sample_paper, monkeypatch, source_url, expected,
):
    from app.services import links_backfill

    sample_paper.pdf_status = "failed"
    sample_paper.openalex_id = "W123"
    db.commit()
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"results": [{
            "id": "https://openalex.org/W123",
            "best_oa_location": {"pdf_url": source_url},
        }]})

    monkeypatch.setattr(links_backfill, "settings", SimpleNamespace(
        openalex_rps=2.0, links_max_batches=1, contact_email="",
    ))
    monkeypatch.setattr(links_backfill, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    result = await links_backfill.run_links_backfill(session_factory)

    assert len(requests) == 1
    assert requests[0].url.host == "api.openalex.org"
    assert requests[0].url.params["filter"] == "openalex:W123"
    assert result["flipped"] == 1
    assert result["openalex_filled"] == int(expected is not None)
    assert result["remaining"] == int(expected is None)
    assert result["paused"] is False
    db.refresh(sample_paper)
    assert sample_paper.pdf_status == "closed"
    assert sample_paper.oa_url == expected
    assert sample_paper.pdf_path is None
    assert sample_paper.pdf_source is None


def test_set_oa_url_if_empty_first_wins(db, sample_paper):
    """oa_url 唯一写入口语义：只在为空时写，先到先得不覆盖。"""
    assert set_oa_url_if_empty(sample_paper, "https://a.example/1") is True
    assert set_oa_url_if_empty(sample_paper, "https://b.example/2") is False
    assert sample_paper.oa_url == "https://a.example/1"
    assert set_oa_url_if_empty(sample_paper, None) is False


def test_best_oa_extraction():
    """links_backfill 的 OpenAlex best OA 提取：pdf_url 优先，回退 oa_url。"""
    from app.services.links_backfill import _best_oa

    assert _best_oa({"best_oa_location": {"pdf_url": "https://x/p.pdf"}}) == "https://x/p.pdf"
    assert _best_oa({"open_access": {"oa_url": "https://y/oa"}}) == "https://y/oa"
    assert _best_oa({"best_oa_location": {}}) is None
    assert _best_oa({}) is None
    assert _best_oa({"open_access": {"oa_url": ""}}) is None  # 空串归一（迭代八）


def test_noise_titles_filtered_at_ingest(db, sample_venue):
    """期刊卷首噪声（editorial board 等）在入库批处理被过滤（迭代八）。"""
    from app.collectors.dblp import RawPaper
    from app.models import Paper
    from app.services.pipeline import CrawlPipeline

    batch = [
        RawPaper(source="openalex", venue_key="W1", title="Editorial Board", year=2025, authors=[]),
        RawPaper(
            source="openalex", venue_key="W2",
            title="IEEE Transactions on Pattern Analysis and Machine Intelligence Information for Authors",
            year=2025, authors=[],
        ),
        RawPaper(source="openalex", venue_key="W3", title="A Real Paper on Agents", year=2025, authors=[]),
    ]
    pipeline = CrawlPipeline.__new__(CrawlPipeline)  # 只用同步入库方法
    papers, created, updated = pipeline._ingest_batch_sync(db, batch, sample_venue, 2025)
    assert created == 1 and updated == 0
    assert papers[0].title == "A Real Paper on Agents"
    assert db.query(Paper).count() == 1


def test_empty_string_oa_url_never_stored(db, sample_venue):
    """OpenAlex 偶返空串：入库归一为 None，不得出现空串 oa_url（迭代八）。"""
    from app.collectors.dblp import RawPaper
    from app.services.pipeline import upsert_paper

    raw = RawPaper(
        source="openalex", venue_key="W77", title="Empty Oa Paper", year=2025,
        authors=[], extra={"oa_pdf": ""},
    )
    paper, _ = upsert_paper(db, raw, sample_venue)
    db.commit()
    assert paper.oa_url is None


def test_stats_uses_group_by_counts(client, sample_paper, db):
    """stats overview 与列表计数一致（GROUP BY 重构后行为不变，迭代五 C3）。"""
    from app.models import Direction, PaperDirection

    specdec = db.query(Direction).filter(Direction.code == "specdec").one()
    db.add(PaperDirection(paper_id=sample_paper.id, direction_id=specdec.id, score=3.0, source="rule"))
    db.commit()

    resp = client.get("/api/stats/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert body["by_direction"]["specdec"] >= 1
    assert body["by_level"]["A"] >= 1
    assert "with_oa_link" in body

    listing = client.get("/api/directions").json()
    spec = next(d for d in listing["items"] if d["code"] == "specdec")
    assert spec["paper_count"] == body["by_direction"]["specdec"]
