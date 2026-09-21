"""FTS5 触发器同步测试（6.2）：insert/update/delete 后 MATCH 结果一致。"""

from app.models import Paper


def _search_count(engine, expr: str) -> int:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT count(*) FROM papers_fts WHERE papers_fts MATCH ?", (expr,)
        ).fetchall()
    return rows[0][0]


def test_fts_sync_on_insert_update_delete(session_factory, db, sample_venue):
    paper = Paper(
        source="dblp",
        dblp_key="conf/nips/fts001",
        title="Quantum Speculative Decoding",
        title_norm="quantum speculative decoding",
        abstract=None,
        venue_id=sample_venue.id,
        year=2024,
        ccf_level="A",
        ccf_area="人工智能",
        official_url="https://example.org",
    )
    db.add(paper)
    db.commit()

    # INSERT → 可命中标题词
    assert _search_count(session_factory.kw["bind"], '"quantum"') == 1

    # UPDATE → 新词命中、旧摘要词消失
    paper.abstract = "unique_abstract_token_alpha"
    db.commit()
    engine = session_factory.kw["bind"]
    assert _search_count(engine, '"unique_abstract_token_alpha"') == 1
    paper.abstract = "replaced_token_beta"
    db.commit()
    assert _search_count(engine, '"unique_abstract_token_alpha"') == 0
    assert _search_count(engine, '"replaced_token_beta"') == 1

    # DELETE → 索引同步删除
    db.delete(paper)
    db.commit()
    assert _search_count(engine, '"replaced_token_beta"') == 0


def test_fts_porter_stemming(session_factory, db, sample_venue):
    paper = Paper(
        source="dblp",
        dblp_key="conf/nips/fts002",
        title="Decoding Methods for Large Models",
        title_norm="decoding methods for large models",
        venue_id=sample_venue.id,
        year=2024,
        ccf_level="A",
        ccf_area="人工智能",
        official_url="https://example.org",
    )
    db.add(paper)
    db.commit()
    engine = session_factory.kw["bind"]
    # porter 词干化：decoded → decod，应命中标题 decoding
    assert _search_count(engine, '"decoded"') == 1
