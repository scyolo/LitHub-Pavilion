from types import SimpleNamespace

import pytest

from app.collectors.journal_conferences import publication_year


def row(issue="POPL"):
    return {
        "DOI": "10.1145/3632895",
        "type": "journal-article",
        "container-title": ["Proceedings of the ACM on Programming Languages"],
        "ISSN": ["2475-1421"],
        "issue": issue,
        "volume": "8",
        "published-print": {"date-parts": [[2024, 1, 2]]},
    }


def test_pacm_issue_identifies_one_conference_and_uses_publication_year():
    v = SimpleNamespace(abbr="POPL", type="conf", ccf_level="A")
    assert publication_year(row(), v) == 2024
    assert publication_year(row("ICFP"), v) is None
    assert (
        publication_year(
            row("OOPSLA1"), SimpleNamespace(abbr="OOPSLA", type="conf", ccf_level="A")
        )
        == 2024
    )


@pytest.mark.parametrize(
    "change",
    [
        {"ISSN": ["0000-0000"]},
        {"container-title": ["ACM SIGPLAN Notices"]},
        {"DOI": "10.9999/3632895"},
        {"issue": "POPL Companion"},
        {"type": "proceedings-article"},
    ],
)
def test_wrong_series_or_non_main_issue_rejected(change):
    value = row()
    value.update(change)
    assert (
        publication_year(
            value, SimpleNamespace(abbr="POPL", type="conf", ccf_level="A")
        )
        is None
    )


def test_dedicated_ches_volume_is_not_cross_assigned_to_other_series():
    value = {
        "DOI": "10.46586/tches.v2025.i1.420-449",
        "type": "journal-article",
        "title": ["Secure hardware"],
        "container-title": [
            "IACR Transactions on Cryptographic Hardware and Embedded Systems"
        ],
        "ISSN": ["2569-2925"],
        "volume": "2025",
        "published": {"date-parts": [[2024, 11, 1]]},
    }
    assert (
        publication_year(
            value, SimpleNamespace(abbr="CHES", type="conf", ccf_level="B")
        )
        == 2025
    )
    assert (
        publication_year(
            value, SimpleNamespace(abbr="FSE (Crypto)", type="conf", ccf_level="B")
        )
        is None
    )
    value["volume"] = "2024"
    assert (
        publication_year(
            value, SimpleNamespace(abbr="CHES", type="conf", ccf_level="B")
        )
        is None
    )


@pytest.mark.parametrize(
    "abbr,issn,title",
    [
        ("SIGMOD", "2836-6573", "Proceedings of the ACM on Management of Data"),
        (
            "SIG- METRICS",
            "2476-1249",
            "Proceedings of the ACM on Measurement and Analysis of Computing Systems",
        ),
        (
            "UbiComp",
            "2474-9567",
            "Proceedings of the ACM on Interactive, Mobile, Wearable and Ubiquitous Technologies",
        ),
    ],
)
def test_officially_linked_journal_series_use_publication_year(abbr, issn, title):
    item = row()
    item.update(ISSN=[issn], **{"container-title": [title]}, issue="1")
    assert (
        publication_year(item, SimpleNamespace(abbr=abbr, type="conf", ccf_level="A"))
        == 2024
    )
    item["ISSN"] = ["0000-0000"]
    assert (
        publication_year(item, SimpleNamespace(abbr=abbr, type="conf", ccf_level="A"))
        is None
    )


def test_verified_pods_doi_never_returns_to_generic_sigmod_series():
    import json
    from pathlib import Path

    proof = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "seeds/pods_verified_publications.json"
        ).read_text(encoding="utf-8")
    )["papers"][0]
    item = {
        "DOI": proof["doi"],
        "type": "journal-article",
        "container-title": ["Proceedings of the ACM on Management of Data"],
        "ISSN": ["2836-6573"],
        "published": {"date-parts": [[proof["event_year"]]]},
    }
    assert (
        publication_year(
            item, SimpleNamespace(abbr="SIGMOD", type="conf", ccf_level="A")
        )
        is None
    )
    assert (
        publication_year(item, SimpleNamespace(abbr="PODS", type="conf", ccf_level="B"))
        == proof["event_year"]
    )
    item["DOI"] = "10.1145/9999999"
    assert (
        publication_year(item, SimpleNamespace(abbr="PODS", type="conf", ccf_level="B"))
        is None
    )
