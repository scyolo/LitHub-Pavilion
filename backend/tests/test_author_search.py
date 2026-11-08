"""Author discovery uses one author's complete token set and indexed paging."""
import pytest
from sqlalchemy import event

from app.api.filtering import PaperFilters
from app.api.routers.search import search
from app.models import Author, Paper, PaperAuthor
from app.services.author_search import author_tokens, normalize_author_name


def add_author(db, paper, name, order):
    author = Author(name=name, name_norm=f"author-{name}-{order}-{paper.id}")
    db.add(author)
    db.flush()
    db.add(PaperAuthor(paper_id=paper.id, author_id=author.id, author_order=order))
    db.commit()
    return author


def test_author_search_matches_nonfirst_authors_order_accents_and_unicode(db, sample_paper):
    add_author(db, sample_paper, "Other, Ada", 1)
    add_author(db, sample_paper, "Béngio, Yoshua", 5)
    add_author(db, sample_paper, "张三", 6)
    for q, matched in [("Yoshua Bengio", ["Béngio, Yoshua"]),
                       ("BENGIO YOSHUA", ["Béngio, Yoshua"]),
                       ("Ｙｏｓｈｕａ Ｂｅｎｇｉｏ", ["Béngio, Yoshua"]),
                       ("张三", ["张三"])]:
        result = search(q=q, filters=PaperFilters(), sort="relevance", page=1, size=20, db=db, match="author")
        assert result["total"] == 1
        assert result["items"][0]["id"] == sample_paper.id
        assert result["items"][0]["matched_authors"] == matched
        assert result["items"][0]["score"] == 0.0
        assert result["match_mode"] == "author"
        assert result["effective_sort"] == "publication_desc"


def test_author_words_cannot_be_combined_across_coauthors(db, sample_paper):
    add_author(db, sample_paper, "Bengio, Samy", 1)
    add_author(db, sample_paper, "Smith, Yoshua", 2)
    result = search(q="Yoshua Bengio", filters=PaperFilters(), sort="relevance", page=1, size=20, db=db, match="author")
    assert result["total"] == 0
    assert result["items"] == []


def test_author_tokens_are_whole_words_without_stemming_or_partial_matching(db, sample_paper):
    add_author(db, sample_paper, "Powers, Alan", 1)
    for q in ("power", "pow", "Al", "ala", 'Powers OR absent'):
        result = search(q=q, filters=PaperFilters(), sort="relevance", page=1, size=20, db=db, match="author")
        assert result["total"] == 0
    assert search(q="Powers", filters=PaperFilters(), sort="year_desc", page=1, size=20, db=db, match="author")["total"] == 1


def test_matching_authors_deduplicate_papers_and_preserve_scope_and_pagination(db, sample_paper, sample_venue):
    add_author(db, sample_paper, "Lee, Alex", 1)
    add_author(db, sample_paper, "Lee, Morgan", 2)
    older = Paper(title="Older work", title_norm="older work", source="manual", doi="10.5555/author-old",
                  official_url="https://doi.org/10.5555/author-old", venue_id=sample_venue.id,
                  year=2023, ccf_level="A", venue_confirmed=1, citation_count=100)
    db.add(older)
    db.commit()
    add_author(db, older, "Lee, Sam", 1)
    for page, ids in [(1, [sample_paper.id]), (2, [older.id]), (3, [])]:
        result = search(q="Lee", filters=PaperFilters(), sort="relevance", page=page, size=1, db=db, match="author")
        assert result["total"] == 2
        assert [item["id"] for item in result["items"]] == ids
    filtered = search(q="Lee", filters=PaperFilters(year=2023), sort="citation_desc", page=1, size=20, db=db, match="author")
    assert filtered["total"] == 1 and filtered["items"][0]["id"] == older.id
    assert search(q="Lee", filters=PaperFilters(venue="missing"), sort="relevance", page=1, size=20, db=db, match="author")["total"] == 0


def test_matching_author_display_names_use_codepoint_order(db, sample_paper):
    add_author(db, sample_paper, "Lee, Zoe", 1)
    add_author(db, sample_paper, "Lee, Ada", 2)
    result = search(q="Lee", filters=PaperFilters(), sort="relevance", page=1, size=20, db=db, match="author")
    assert result["items"][0]["matched_authors"] == ["Lee, Ada", "Lee, Zoe"]


@pytest.mark.parametrize("query", ["", "  ", "!!!", "a" * 201, " ".join(["name"] * 13)])
def test_invalid_author_queries_are_client_errors(client, query):
    response = client.get("/api/search", params={"q": query, "match": "author"})
    assert response.status_code == 400


def test_author_api_returns_name_matches(client, db, sample_paper):
    add_author(db, sample_paper, "Lovelace, Ada", 7)
    response = client.get("/api/search", params={"q": "Ada Lovelace", "match": "author"})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["matched_authors"] == ["Lovelace, Ada"]


def test_uninitialized_author_index_is_reported_without_hiding_data(client, db, sample_paper):
    add_author(db, sample_paper, "Lovelace, Ada", 1)
    db.connection().exec_driver_sql('DROP TABLE authors_search_fts')
    db.commit()
    response = client.get('/api/search', params={'q': 'Ada Lovelace', 'match': 'author'})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'AUTHOR_INDEX_UNAVAILABLE'
    assert client.get('/api/search', params={'q': 'decoding', 'match': 'keywords'}).json()['total'] == 1


def test_author_index_updates_and_rollback_are_transactional(db, sample_paper):
    author = add_author(db, sample_paper, "Grace Hopper", 1)

    def total(q):
        return search(q=q, filters=PaperFilters(), sort="relevance", page=1, size=20, db=db, match="author")["total"]

    assert total("Grace Hopper") == 1
    author.name = "Ada Lovelace"
    db.flush()
    assert total("Ada Lovelace") == 1 and total("Grace Hopper") == 0
    db.rollback()
    assert total("Grace Hopper") == 1 and total("Ada Lovelace") == 0
    db.delete(author)
    db.commit()
    assert total("Grace Hopper") == 0


def test_author_search_uses_reverse_author_index_and_only_loads_page_metadata(db, engine, sample_paper):
    add_author(db, sample_paper, "Knuth, Donald", 1)
    statements = []

    def capture(_conn, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = search(q="Donald Knuth", filters=PaperFilters(), sort="relevance", page=1, size=1, db=db, match="author")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["total"] == 1
    windows = [(sql, params) for sql, params in statements if "count(*) OVER" in sql]
    assert len(windows) == 1
    assert "papers.abstract AS" not in windows[0][0]
    plan = db.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + windows[0][0], windows[0][1]).all()
    assert any("ix_paper_authors_author" in row[3] for row in plan)
    assert not any("bm25(" in sql for sql, _ in statements)


@pytest.mark.parametrize("name,expected", [
    ("  Béngio, Ｙｏｓｈｕａ  ", "bengio yoshua"),
    ("O’Neil, Anne-Marie", "o neil anne marie"),
    ("张三", "张三"),
    ("İşık ǰ", "isık j"),
    ("नमस्ते कुमार", "नमसत कमर"),
    ('\u1c89 Smith', 'smith'),
    ('\U0001e4d0 Smith', 'smith'),
    ('Ⓐda Ⅲ', 'ada iii'),
    ('ΟΣ', 'ος'),
])
def test_author_normalization_keeps_unicode_name_parts(name, expected):
    assert normalize_author_name(name) == expected
    assert author_tokens(name) == tuple(dict.fromkeys(expected.split()))


def test_browser_and_api_bundle_identical_unicode_search_contract():
    import json
    from pathlib import Path

    root=Path(__file__).resolve().parents[2]
    assert json.loads((root/'backend/app/services/author_unicode.json').read_text('utf-8')) == json.loads(
        (root/'frontend/src/data/author_unicode.json').read_text('utf-8'))


def test_bootstrap_adds_author_index_after_backup_and_preserves_existing_rows(
    db, engine, sample_paper, monkeypatch
):
    from app import bootstrap

    author = add_author(db, sample_paper, "Ｂéngio, Yoshua", 3)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER authors_search_fts_ai")
        connection.exec_driver_sql("DROP TRIGGER authors_search_fts_au")
        connection.exec_driver_sql("DROP TRIGGER authors_search_fts_ad")
        connection.exec_driver_sql("DROP TABLE authors_search_fts")
        connection.exec_driver_sql("DROP INDEX ix_paper_authors_author")
    backups = []

    def backup(target):
        with target.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE name='authors_search_fts'").first() is None
            assert connection.exec_driver_sql("SELECT count(*) FROM authors").scalar() == 1
        backups.append(target)

    monkeypatch.setattr(bootstrap, "_backup", backup)
    monkeypatch.setattr(bootstrap, "seed_missing", lambda _session, _directory: None)
    bootstrap.initialize_database(engine)
    bootstrap.initialize_database(engine)
    assert backups == [engine]
    assert db.get(Author, author.id).name == "Ｂéngio, Yoshua"
    result = search(q="Yoshua Bengio", filters=PaperFilters(), sort="relevance", page=1, size=20, db=db, match="author")
    assert result["total"] == 1
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM authors_search_fts").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_author_index_rebuild_restores_missing_rows_without_changing_names(db, sample_paper):
    from app.services.author_search import rebuild_author_search

    author = add_author(db, sample_paper, "Turing, Alan", 1)
    db.connection().exec_driver_sql("DELETE FROM authors_search_fts")
    db.commit()
    assert search(q="Alan Turing", filters=PaperFilters(), sort="relevance", page=1, size=20, db=db, match="author")["total"] == 0
    rebuild_author_search(db.connection())
    db.commit()
    assert search(q="Alan Turing", filters=PaperFilters(), sort="relevance", page=1, size=20, db=db, match="author")["total"] == 1
    assert db.get(Author, author.id).name == "Turing, Alan"


def test_failed_author_backfill_does_not_leave_empty_index_to_reuse(
    db, engine, sample_paper, monkeypatch
):
    from app import bootstrap
    from app.services import author_search

    add_author(db, sample_paper, "Turing, Alan", 1)
    with engine.begin() as connection:
        for name in ["authors_search_fts_ai", "authors_search_fts_au", "authors_search_fts_ad"]:
            connection.exec_driver_sql("DROP TRIGGER " + name)
        connection.exec_driver_sql("DROP TABLE authors_search_fts")
    monkeypatch.setattr(bootstrap, "_backup", lambda _engine: None)
    monkeypatch.setattr(bootstrap, "seed_missing", lambda _session, _directory: None)
    original = author_search.rebuild_author_search

    def fail(_connection):
        raise RuntimeError("failed backfill")

    monkeypatch.setattr(author_search, "rebuild_author_search", fail)
    with pytest.raises(RuntimeError, match="failed backfill"):
        bootstrap.initialize_database(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE name='authors_search_fts'").first() is None
    monkeypatch.setattr(author_search, "rebuild_author_search", original)
    bootstrap.initialize_database(engine)
    assert search(q="Alan Turing", filters=PaperFilters(), sort="relevance", page=1, size=20, db=db, match="author")["total"] == 1
