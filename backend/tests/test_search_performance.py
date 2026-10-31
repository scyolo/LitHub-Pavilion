"""Keep FTS ranking work bounded without changing search results or scores."""

import pytest
from sqlalchemy import event

from app.api.filtering import PaperFilters
from app.api.routers.search import _build_match_expr, search
from app.cleaning import normalize_title
from app.models import Paper


def test_search_does_not_restart_fts_for_each_candidate(db, engine, sample_paper):
    statements = []

    def capture(_conn, _cursor, statement, parameters, _context, _many):
        if "bm25(" in statement:
            statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = search(q="decoding", filters=PaperFilters(), sort="relevance",
                        page=1, size=20, db=db, match="keywords")
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert result["items"][0]["id"] == sample_paper.id
    assert statements
    for sql, parameters in statements:
        plan = db.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + sql, parameters)
        assert not any("CORRELATED SCALAR SUBQUERY" in row[3] for row in plan), (
            "Per-candidate FTS cursors recompute corpus statistics and make broad searches quadratic"
        )


def test_filtered_pagination_preserves_global_bm25(db, sample_paper, sample_venue):
    rows = [
        ("Parallel decoding", "decoding " * 6, 2024),
        ("Decoding outside the selected year", "decoding " * 20, 2025),
        *[(f"Unrelated background article {index}", "Different subject", 2024)
          for index in range(8)],
    ]
    for index, (title, abstract, year) in enumerate(rows):
        db.add(Paper(source="manual", title=title, title_norm=normalize_title(title),
                     abstract=abstract, year=year, venue_id=sample_venue.id,
                     ccf_level="A", venue_confirmed=1,
                     doi=f"10.5555/ranking-{index}",
                     official_url=f"https://doi.org/10.5555/ranking-{index}"))
    db.commit()
    scores = dict(db.connection().exec_driver_sql(
        "SELECT rowid, bm25(papers_fts, 8.0, 1.0) FROM papers_fts WHERE papers_fts MATCH ?",
        (_build_match_expr("decoding"),),
    ).all())
    public_ids = {pid for pid, in db.query(Paper.id).filter(Paper.year == 2024)}
    expected = sorted(public_ids & scores.keys(), key=lambda pid: (scores[pid], -pid))
    assert len(expected) == 2
    for page in (1, 2, 3):
        result = search(q="decoding", filters=PaperFilters(year=2024), sort="relevance",
                        page=page, size=1, db=db, match="keywords")
        assert result["total"] == len(expected)
        assert [item["id"] for item in result["items"]] == expected[page - 1:page]
        for item in result["items"]:
            assert item["score"] == round(scores[item["id"]], 4)


@pytest.mark.parametrize("identity,change", [
    ({"doi": "10.5555/cached"}, {"title": "Preface"}),
    ({"doi": "10.5555/cached"}, {"doi": "10.48550/arxiv.2501.12345"}),
    ({"publisher_key": "https://publisher.example/article"},
     {"publisher_key": "https://arxiv.org/abs/2501.12345"}),
    ({"dblp_key": "conf/nips/Cached2024"}, {"dblp_key": "conf/icml/Cached2024"}),
    ({"dblp_key": "conf/nips/Cached2024"}, {"stream": "conf/icml"}),
])
def test_cached_eligibility_uses_current_metadata(db, sample_paper, sample_venue, identity, change):
    sample_paper.source = "dblp" if "dblp_key" in identity else "manual"
    for field in ("doi", "publisher_key", "dblp_key"):
        setattr(sample_paper, field, identity.get(field))
    db.commit()

    def total():
        return search(q="decoding", filters=PaperFilters(), sort="relevance",
                      page=1, size=20, db=db, match="keywords")["total"]

    assert total() == total() == 1
    for field, value in change.items():
        if field == "stream":
            sample_venue.dblp_stream = value
        else:
            setattr(sample_paper, field, value)
    db.commit()
    assert total() == 0
