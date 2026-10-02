from types import SimpleNamespace

import pytest

from app.collectors.catalog_books import book_year, chapter_year


def parent(**changes):
    value = {
        "DOI": "10.1007/978-3-032-12287-2",
        "type": "book",
        "title": ["Theory of Cryptography"],
        "subtitle": [
            "23rd International Conference, TCC 2025, Aarhus, Denmark, December 1–5, 2025, Proceedings, Part I"
        ],
        "ISBN": ["9783032122872"],
    }
    value.update(changes)
    return value


def test_book_event_year_not_imprint_and_chapter_identity():
    p = parent()
    v = SimpleNamespace(abbr="TCC", type="conf", ccf_level="A")
    assert book_year(p, "TCC") == 2025
    row = {
        "DOI": p["DOI"] + "_1",
        "type": "book-chapter",
        "container-title": [
            "Lecture Notes in Computer Science",
            "Theory of Cryptography",
        ],
        "_catalog_book_parent": p,
        "published": {"date-parts": [[2026]]},
    }
    assert chapter_year(row, v) == 2025
    row["DOI"] = "10.1007/978-0-000-00000-0_1"
    assert chapter_year(row, v) is None


@pytest.mark.parametrize(
    "change",
    [
        {"subtitle": ["TCC 2025 Workshops, Proceedings"]},
        {"subtitle": ["TCC 2025, 2024, Proceedings"]},
        {"subtitle": ["Proceedings 2025"]},
        {"title": ["Unrelated book"]},
        {"DOI": "10.9999/book"},
    ],
)
def test_book_requires_explicit_source_year_main_proceedings(change):
    assert book_year(parent(**change), "TCC") is None


def test_cryptology_title_has_acronym_and_cade_has_edition_not_year():
    p = parent(
        title=["Advances in Cryptology – CRYPTO 2024"],
        subtitle=[
            "44th Annual International Cryptology Conference, August 18–22, 2024, Proceedings, Part VI"
        ],
    )
    assert book_year(p, "CRYPTO") == 2024
    assert book_year(p, "EUROCRYPT") is None
    p = parent(
        title=["Automated Deduction – CADE 30"],
        subtitle=[
            "30th International Conference on Automated Deduction, July 28–31, 2025, Proceedings"
        ],
    )
    assert book_year(p, "CADE") == 2025


def test_publisher_import_uses_parent_event_year(db):
    from app.models import Paper, Venue
    from app.services.publisher_metadata import apply_items

    v = Venue(
        abbr="TCC",
        name="Theory of Cryptography Conference",
        type="conf",
        ccf_level="B",
        active=1,
    )
    db.add(v)
    db.commit()
    p = parent()
    row = {
        "DOI": p["DOI"] + "_1",
        "type": "book-chapter",
        "title": ["Secure cryptographic protocols"],
        "author": [{"given": "Ada", "family": "Lee"}],
        "container-title": [
            "Lecture Notes in Computer Science",
            "Theory of Cryptography",
        ],
        "_catalog_book_parent": p,
        "published": {"date-parts": [[2026]]},
    }
    result = apply_items(db, [row], [2025])
    assert result["counts"].get("new") == 1
    paper = db.query(Paper).one()
    assert paper.year == 2025 and paper.venue_confirmed == 1


def test_etaps_requires_explicit_umbrella_conference_in_parent():
    value=parent(title=['Tools and Algorithms for the Construction and Analysis of Systems'],subtitle=['29th International Conference, TACAS 2023, Held as Part of ETAPS 2023, Paris, Proceedings, Part I'])
    assert book_year(value,'ETAPS')==2023
    value['subtitle']=['TACAS 2023 Proceedings']
    assert book_year(value,'ETAPS') is None
