import pytest

from app.collectors.dagstuhl_catalog import parse_record


def record():
    return {
        "id": "10.4230/lipics.socg.2024.11",
        "attributes": {
            "doi": "10.4230/lipics.socg.2024.11",
            "publisher": "Schloss Dagstuhl – Leibniz-Zentrum für Informatik",
            "titles": [{"title": "Geometric graph algorithms"}],
            "creators": [{"name": "Lee, Ada"}],
            "types": {"resourceTypeGeneral": "ConferencePaper"},
            "container": {"identifier": "10.4230/LIPIcs.SoCG.2024"},
            "url": "https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.SoCG.2024.11",
            "publicationYear": 2024,
        },
    }


def test_registered_proceedings_identity_and_authors():
    row = parse_record(record(), "SoCG", 2024)
    assert row.title == "Geometric graph algorithms" and row.year == 2024
    assert row.doi == "10.4230/lipics.socg.2024.11"
    assert row.extra["publisher_key"].startswith("https://drops.dagstuhl.de/")


@pytest.mark.parametrize(
    "field,value",
    [
        ("doi", "10.4230/lipics.socg.2023.11"),
        ("publisher", "Unrelated"),
        ("container", {"identifier": "10.4230/LIPIcs.ESA.2024"}),
        ("types", {"resourceTypeGeneral": "ConferenceProceeding"}),
        ("titles", [{"title": "Front Matter, Table of Contents, Preface"}]),
        ("titles", [{"title": "Geometric computation (Invited Talk)"}]),
        ("url", "https://example.com/paper.pdf"),
    ],
)
def test_wrong_edition_book_or_nonresearch_is_not_a_paper(field, value):
    item = record()
    item["attributes"][field] = value
    assert parse_record(item, "SoCG", 2024) is None
