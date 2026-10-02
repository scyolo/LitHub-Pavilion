from types import SimpleNamespace

import pytest

from app.collectors.crossref import identify_venue
from app.collectors.journal_serials import serial_sources


def venue(abbr, name, issn):
    return SimpleNamespace(
        abbr=abbr, name=name, issn=issn, type="journal", ccf_level="A"
    )


@pytest.mark.parametrize(
    "v,issn,title",
    [
        (
            venue("TON", "IEEE Transactions on Networking", "2998-4157"),
            "1063-6692",
            "IEEE/ACM Transactions on Networking",
        ),
        (
            venue("INFORMS", "INFORMS Journal on Computing", "0899-1499"),
            "1091-9856",
            "INFORMS Journal on Computing",
        ),
        (
            venue("Evolutionary Computation", "Evolutionary Computation", "1063-6560"),
            "1530-9304",
            "Evolutionary Computation",
        ),
    ],
)
def test_exact_registry_serials_recover_older_records_without_fuzzy_identity(
    v, issn, title
):
    row = {
        "DOI": "10.1109/serial.test",
        "type": "journal-article",
        "ISSN": [issn],
        "container-title": [title],
        "published": {"date-parts": [[2023]]},
    }
    assert identify_venue(row, {v.abbr: v}) is v
    v.name = "An unrelated journal"
    assert serial_sources(v) == []
    assert identify_venue(row, {v.abbr: v}) is None


def test_historical_serial_fetch_has_an_explicit_year_bound():
    v = venue("TON", "IEEE Transactions on Networking", "2998-4157")
    assert any(
        r["issn"] == "1063-6692" and r["year_to"] == 2024 for r in serial_sources(v)
    )
    v.issn = "0000-0000"
    assert serial_sources(v) == []


def test_serial_items_reject_wrong_identity_year_and_nonarticle_types():
    from app.collectors.journal_serials import valid_serial_item

    spec = {
        "issn": "1063-6692",
        "title": "IEEE/ACM Transactions on Networking",
        "year_from": 2023,
        "year_to": 2024,
    }
    row = {
        "DOI": "10.1109/tnet.2023.1234",
        "type": "journal-article",
        "ISSN": ["1063-6692"],
        "container-title": [spec["title"]],
        "published-print": {"date-parts": [[2024]]},
    }
    assert valid_serial_item(row, spec)
    assert not valid_serial_item({**row, "type": "dataset"}, spec)
    assert not valid_serial_item(
        {**row, "published-print": {"date-parts": [[2025]]}}, spec
    )
    assert not valid_serial_item({**row, "ISSN": ["9999-9999"]}, spec)
    assert not valid_serial_item({**row, "container-title": ["Unrelated source"]}, spec)
