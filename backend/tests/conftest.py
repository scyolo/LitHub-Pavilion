"""共享测试夹具：临时 SQLite 库 + FTS 表 + API TestClient。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db import _make_engine
from app.models import Author, Base, Direction, FTS_DDL, Paper, PaperAuthor, PaperDirection, Venue


@pytest.fixture()
def engine(tmp_path):
    return _make_engine("sqlite:///" + str(tmp_path / "test.db").replace("\\", "/"))


@pytest.fixture()
def session_factory(engine):
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        for ddl in FTS_DDL:
            conn.exec_driver_sql(" ".join(ddl.split()))
        conn.commit()
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def sample_venue(db) -> Venue:
    venue = Venue(
        abbr="NeurIPS",
        name="Annual Conference on Neural Information Processing Systems",
        dblp_stream="conf/nips",
        dblp_toc_pattern="nips{year}",
        type="conf",
        ccf_level="A",
        ccf_area="人工智能",
        active=1,
    )
    db.add(venue)
    db.commit()
    return venue


@pytest.fixture()
def sample_direction(db) -> Direction:
    direction = Direction(code="specdec", name="投机解码", min_score=2.0, enabled=1)
    db.add(direction)
    db.commit()
    return direction


@pytest.fixture()
def sample_paper(db, sample_venue, sample_direction) -> Paper:
    paper = Paper(
        source="dblp",
        dblp_key="conf/nips/test2024fast",
        title="Fast Inference via Speculative Decoding",
        title_norm="fast inference via speculative decoding",
        abstract="We accelerate decoding with a draft model.",
        venue_id=sample_venue.id,
        year=2024,
        ccf_level="A",
        ccf_area="人工智能",
        doi="10.5555/test.001",
        official_url="https://doi.org/10.5555/test.001",
        pdf_status="pending",
        venue_confirmed=1,
    )
    db.add(paper)
    db.commit()
    return paper


@pytest.fixture()
def client(engine, session_factory, monkeypatch):
    """TestClient：把 app.db 全局引擎/会话工厂指向测试库，禁用真实调度。"""
    import app.api.main as main_module
    import app.db as db_module

    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_SessionLocal", session_factory)
    monkeypatch.setattr(main_module, "start_scheduler", lambda pipeline: None)
    monkeypatch.setattr(main_module.settings, "initialize_on_startup", False)
    monkeypatch.setattr(main_module.settings, "startup_crawl_enabled", False)
    monkeypatch.setattr(main_module.settings, "snapshot_enabled", False)
    monkeypatch.setattr(main_module.settings, "pages_publish_enabled", False)
    monkeypatch.setattr(main_module.settings, "snapshot_state_file", Path(engine.url.database).parent / "private-receipt.json")

    app = main_module.create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def api_catalog(db):
    """含零数据 venue、多标签、脏历史 scope 的隔离 API 样本；ID 故意不对齐。"""
    now = datetime.now(timezone.utc)
    venues = [
        Venue(id=101, abbr="AC", name="A Conference", dblp_stream="conf/ac", type="conf", ccf_level="A"),
        Venue(id=203, abbr="BC", name="B Conference", dblp_stream="conf/bc", type="conf", ccf_level="B"),
        Venue(id=305, abbr="AJ", name="A Journal", dblp_stream="journals/aj", type="journal", ccf_level="A"),
        Venue(id=407, abbr="BJ", name="B Journal", dblp_stream="journals/bj", type="journal", ccf_level="B", active=0),
        Venue(id=509, abbr="EMPTY", name="Empty Journal", dblp_stream="journals/empty", type="journal", ccf_level="B"),
    ]
    directions = [
        Direction(id=21, code="specdec", name="投机解码"),
        Direction(id=32, code="llm", name="大语言模型"),
        Direction(id=43, code="agent", name="智能体"),
        Direction(id=54, code="unused", name="暂无论文"),
    ]
    db.add_all(venues + directions)
    db.flush()
    # id, venue, year, 入库距今天数, oa_url, arxiv_id, abstract, confirmed, citations
    cases = [
        (11, venues[0], 2024, 1, " https://oa.example.org/11 ", None, "x" * 500, 1, 5),
        (23, venues[1], 2023, 9, None, "2302.12345v2", None, 0, 10),
        (35, venues[2], now.year, 3, " \n\t", None, " \n\t", 1, 0),
        (47, venues[3], 2025, 12, "javascript:alert(1)", None, None, 0, 3),
        (59, venues[0], now.year, -1, "http://oa.example.org/59", None, "Summary", 0, 5),
        (71, venues[1], 2024, 2, "https://user:pass@oa.example.org/71", None, "Summary", 1, 0),
        (83, venues[0], 2023, 6, "http://127.0.0.1/83", "2301.00456", None, 0, 1),
    ]
    papers = []
    for pid, venue, year, days, oa_url, arxiv_id, abstract, confirmed, citations in cases:
        paper = Paper(
            id=pid, source="dblp", dblp_key=f"{venue.dblp_stream}/paper{pid}1999",
            title="Radar model", title_norm="radar model", abstract=abstract,
            venue_id=venue.id, year=year, ccf_level=venue.ccf_level,
            official_url=f"https://publisher.example.org/{pid}", oa_url=oa_url,
            arxiv_id=arxiv_id, venue_confirmed=confirmed, citation_count=citations,
            created_at=(now - timedelta(days=days)).isoformat(timespec="seconds"),
            publication_date=now.date().isoformat() if pid == 23 else None,
            pdf_status="downloaded" if pid == 71 else "closed",
        )
        papers.append(paper)
    papers[0].doi = " HTTPS://DX.DOI.ORG/10.5555/RADAR.11 "
    db.add_all(papers)
    db.flush()
    for pid, codes in {
        11: (21, 32), 23: (21,), 35: (32,), 47: (43,),
        59: (32,), 71: (32,), 83: (21, 43),
    }.items():
        for direction_id in codes:
            db.add(PaperDirection(paper_id=pid, direction_id=direction_id))
    for order, name in [(4, "Fourth"), (2, "Second"), (1, "First"), (3, "Third")]:
        author = Author(name=name, name_norm=name.lower())
        db.add(author)
        db.flush()
        db.add(PaperAuthor(paper_id=11, author_id=author.id, author_order=order))
    db.flush()

    # 只在临时测试连接上模拟旧库脏数据；正常应用 CHECK 约束不改动。
    db.execute(text("PRAGMA ignore_check_constraints = ON"))
    try:
        hidden_venues = [
            Venue(id=611, abbr="HIDDEN_C", name="Hidden C", dblp_stream="conf/c", type="conf", ccf_level="C"),
            Venue(id=713, abbr="HIDDEN_TYPE", name="Hidden Type", dblp_stream="conf/other", type="workshop", ccf_level="A"),
            Venue(id=815, abbr="HIDDEN_LEVEL", name="Hidden Level", dblp_stream="journals/other", type="journal", ccf_level="unknown"),
        ]
        db.add_all(hidden_venues)
        db.flush()
        hidden_ids = []
        for pid, venue_id, level in [(95, 101, "C"), (107, 611, "A"), (119, 713, "A"), (131, 101, "unknown"), (143, 815, "A")]:
            db.add(Paper(
                id=pid, source="dblp", dblp_key=f"conf/hidden/{pid}",
                title="Radar model", title_norm="radar model", year=2024,
                venue_id=venue_id, ccf_level=level,
                official_url="https://publisher.example.org/hidden",
                oa_url="https://oa.example.org/hidden",
            ))
            hidden_ids.append(pid)
        db.flush()
        db.add_all(PaperDirection(paper_id=pid, direction_id=21) for pid in hidden_ids)
        db.flush()
    finally:
        db.execute(text("PRAGMA ignore_check_constraints = OFF"))
    db.commit()
    return {"papers": papers, "venues": venues, "hidden_ids": hidden_ids, "now": now}
