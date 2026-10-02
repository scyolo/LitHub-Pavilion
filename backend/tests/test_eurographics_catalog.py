from app.collectors.eurographics_catalog import collection_identity, parse_item


def test_collection_identity_requires_explicit_conference_not_regular_issue():
    c = {
        "name": "43-Issue 2",
        "metadata": {
            "dc.description.abstract": [{"value": "EG 2024 - Conference Issue"}]
        },
    }
    assert collection_identity(c) == ("Eurographics", 2024, "43", "2")
    c["metadata"]["dc.description.abstract"][0]["value"] = "Regular Issue"
    assert collection_identity(c) is None


def test_journal_item_requires_issue_doi_publisher_and_authors():
    m = {
        "dc.title": [{"value": "Geometric models"}],
        "dc.date.issued": [{"value": "2024"}],
        "dc.description.volume": [{"value": "43"}],
        "dc.description.number": [{"value": "2"}],
        "dc.identifier.doi": [{"value": "10.1111/cgf.15046"}],
        "dc.identifier.issn": [{"value": "1467-8659"}],
        "dc.publisher": [
            {"value": "The Eurographics Association and John Wiley & Sons Ltd."}
        ],
        "dc.contributor.author": [{"value": "Lee, Ada", "place": 0}],
    }
    assert parse_item({"metadata": m}, 2024, "43", "2").doi == "10.1111/cgf.15046"
    m["dc.description.number"][0]["value"] = "3"
    assert parse_item({"metadata": m}, 2024, "43", "2") is None


def test_missing_issue_fields_require_separately_verified_owning_collection():
    m = {
        "dc.title": [{"value": "Geometry"}],
        "dc.date.issued": [{"value": "2025"}],
        "dc.identifier.doi": [{"value": "10.1111/cgf.70103"}],
        "dc.identifier.issn": [{"value": "1467-8659"}],
        "dc.publisher": [
            {"value": "The Eurographics Association and John Wiley & Sons Ltd."}
        ],
        "dc.contributor.author": [{"value": "Lee, Ada", "place": 0}],
    }
    item = {"metadata": m}
    assert parse_item(item, 2025, "44", "3") is None
    assert (
        parse_item(item, 2025, "44", "3", verified_membership=True).doi
        == "10.1111/cgf.70103"
    )
    m["dc.description.number"] = [{"value": "2"}]
    assert parse_item(item, 2025, "44", "3", verified_membership=True) is None
