"""Keep FTS ranking work bounded without changing search results or scores."""

import pytest
from sqlalchemy import event

from app.api.filtering import PaperFilters
from app.api.routers.search import _build_match_expr, search
from app.cleaning import normalize_title
from app.models import Paper, PaperDirection


@pytest.mark.parametrize("mode", ["auto", "keywords", "fuzzy", "exact"])
def test_search_filters_matching_metadata_once(db, sample_paper, monkeypatch, mode):
    from app.services import publication_admission

    original = publication_admission._eligible_metadata
    checked = []

    def eligible(*metadata):
        checked.append(metadata)
        return original(*metadata)

    monkeypatch.setattr(publication_admission, "_eligible_metadata", eligible)
    q = sample_paper.title if mode == "exact" else "decoding"
    result = search(q=q, filters=PaperFilters(), sort="relevance",
                    page=1, size=20, db=db, match=mode)
    assert result["total"] == 1
    assert len(checked) == 1, "Counting and pagination must share the filtered candidates"


def test_auto_past_last_page_retains_total_without_fuzzy_fallback(db, sample_paper):
    result = search(q="decoding", filters=PaperFilters(), sort="relevance",
                    page=2, size=20, db=db, match="auto")
    assert result["total"] == 1
    assert result["items"] == []
    assert result["match_mode"] == "keywords"


def test_topic_search_pages_ids_before_loading_paper_metadata(
    db, engine, sample_paper, sample_venue, sample_direction
):
    other = Paper(source="manual", title="Earlier decoding study",
                  title_norm="earlier decoding study", abstract="metadata " * 1000,
                  year=2023, venue_id=sample_venue.id, ccf_level="A", venue_confirmed=1,
                  doi="10.5555/topic-page", official_url="https://doi.org/10.5555/topic-page")
    db.add(other)
    db.flush()
    db.add_all(PaperDirection(paper_id=pid, direction_id=sample_direction.id)
               for pid in (sample_paper.id, other.id))
    db.commit()
    windows = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if "count(*) OVER" in statement:
            windows.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        for page, expected_ids in ((1, [sample_paper.id]), (2, [other.id]), (3, [])):
            result = search(q="投机解码", filters=PaperFilters(), sort="relevance",
                            page=page, size=1, db=db, match="auto")
            assert result["total"] == 2
            assert [item["id"] for item in result["items"]] == expected_ids
            assert result["match_mode"] == "topic"
            assert result["effective_sort"] == "publication_desc"
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(windows) == 3
    assert all("papers.abstract AS" not in sql and "papers.title AS" not in sql for sql in windows)


def test_date_order_scores_only_the_page_with_global_bm25(db, engine, sample_paper, sample_venue):
    for index in range(8):
        title = f"Decoding method {index}"
        db.add(Paper(source="manual", title=title, title_norm=normalize_title(title),
                     abstract="decoding " * (index + 1), year=2023,
                     venue_id=sample_venue.id, ccf_level="A", venue_confirmed=1,
                     doi=f"10.5555/page-score-{index}",
                     official_url=f"https://doi.org/10.5555/page-score-{index}"))
    db.commit()
    expected = dict(db.connection().exec_driver_sql(
        "SELECT rowid, bm25(papers_fts, 8.0, 1.0) FROM papers_fts WHERE papers_fts MATCH ?",
        (_build_match_expr("decoding"),),
    ).all())
    statements = []

    def capture(_conn, _cursor, statement, parameters, _context, _many):
        if "bm25(" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = search(q="decoding", filters=PaperFilters(), sort="year_desc",
                        page=1, size=1, db=db, match="keywords")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["total"] == 9
    assert result["items"][0]["id"] == sample_paper.id
    assert result["items"][0]["score"] == round(expected[sample_paper.id], 4)
    assert len(statements) == 1
    assert "rowid IN" in statements[0], "Other sort orders only need page-sized BM25 work"


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
