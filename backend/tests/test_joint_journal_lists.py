import pytest

from app.collectors.joint_journal_lists import (
    match_registry_paper,
    parse_publication_list,
)


def test_pods_list_requires_source_heading_and_full_author_names():
    text = '<div id="maincontent"><h1>PODS 2024: Accepted Papers</h1><li><strong>Query optimization</strong><br>Alice Lee, Robert Smith and Carol Ng</li></div>'
    rows = parse_publication_list(text, "PODS", 2024)
    assert rows[0]["title"] == "Query optimization"
    assert rows[0]["authors"] == ["Lee, Alice", "Smith, Robert", "Ng, Carol"]
    with pytest.raises(ValueError):
        parse_publication_list(text, "PODS", 2025)


def test_conext_list_removes_affiliations_not_author_initials():
    text = "<h2>CoNEXT 2023 Accepted Papers</h2><ol><li><b>Network research</b><br>A. Lee <em>(University, Country)</em>, R. Smith <em>(Lab)</em></li></ol>"
    row = parse_publication_list(text, "CoNEXT", 2023)[0]
    assert row["authors"] == ["Lee, A.", "Smith, R."]
    item = {
        "DOI": "10.1145/1234567",
        "type": "journal-article",
        "title": ["Network research"],
        "container-title": ["Proceedings of the ACM on Networking"],
        "ISSN": ["2834-5509"],
        "published": {"date-parts": [[2023]]},
        "author": [
            {"given": "Alice", "family": "Lee"},
            {"given": "Robert", "family": "Smith"},
        ],
    }
    assert match_registry_paper(row, [item], "CoNEXT") == item
    assert (
        match_registry_paper(row, [{**item, "ISSN": ["1111-1111"]}], "CoNEXT") is None
    )
    assert (
        match_registry_paper(row, [{**item, "title": ["Unrelated title"]}], "CoNEXT")
        is None
    )
    assert (
        match_registry_paper(row, [item, {**item, "DOI": "10.1145/7654321"}], "CoNEXT")
        is None
    )


def test_same_initial_different_full_name_fails_closed():
    row = {"title": "Query optimization", "authors": ["Lee, Alice", "Smith, Robert"]}
    item = {
        "DOI": "10.1145/1234567",
        "type": "journal-article",
        "title": ["Query optimization"],
        "container-title": ["Proceedings of the ACM on Management of Data"],
        "ISSN": ["2836-6573"],
        "published": {"date-parts": [[2024]]},
        "author": [
            {"given": "Adam", "family": "Lee"},
            {"given": "Robert", "family": "Smith"},
        ],
    }
    assert match_registry_paper(row, [item], "PODS") is None


def test_pods_2025_year_is_verified_from_official_conference_page_title():
    text = '<title>The 2025 ACM SIGMOD/PODS Conference: Berlin, Germany - Accepted Papers for PODS</title><div id="maincontent"><h1>Accepted Papers for PODS</h1><ul><li><b>Query optimization</b><br>Alice Lee and Robert Smith</li></ul></div>'
    assert len(parse_publication_list(text, "PODS", 2025)) == 1
    with pytest.raises(ValueError):
        parse_publication_list(text, "PODS", 2024)
    with pytest.raises(ValueError):
        parse_publication_list(text.replace("SIGMOD/PODS", "Other"), "PODS", 2025)
