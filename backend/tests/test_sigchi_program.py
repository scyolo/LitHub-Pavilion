import pytest

from app.collectors.sigchi_program import match_hci_publication, program_papers


def document():
    return {
        "conference": {
            "shortName": "CSCW",
            "year": 2025,
            "url": "https://cscw.acm.org/2025/",
        },
        "contentTypes": [{"id": 1, "name": "Paper"}, {"id": 2, "name": "Poster"}],
        "people": [
            {"id": 10, "firstName": "Ada", "lastName": "Lee"},
            {"id": 11, "firstName": "Bob", "lastName": "Smith"},
        ],
        "contents": [
            {
                "id": 100,
                "typeId": 1,
                "title": "Collaborative Systems",
                "authors": [{"personId": 10}, {"personId": 11}],
            },
            {
                "id": 101,
                "typeId": 2,
                "title": "Poster Systems",
                "authors": [{"personId": 10}],
            },
        ],
    }


def test_public_program_rejects_wrong_edition_and_excludes_posters():
    papers = program_papers(document(), "CSCW", 2025)
    assert len(papers) == 1 and papers[0]["authors"] == ["Lee, Ada", "Smith, Bob"]
    with pytest.raises(ValueError):
        program_papers(document(), "CSCW", 2024)
    data = document()
    data["conference"]["url"] = "https://unrelated.example/2025/"
    with pytest.raises(ValueError):
        program_papers(data, "CSCW", 2025)


def metadata(**changes):
    row = {
        "DOI": "10.1145/1234567",
        "title": ["Collaborative Systems"],
        "author": [
            {"given": "Ada", "family": "Lee"},
            {"given": "Bob", "family": "Smith"},
        ],
        "type": "journal-article",
        "ISSN": ["2573-0142"],
        "container-title": ["Proceedings of the ACM on Human-Computer Interaction"],
        "published": {"date-parts": [[2025]]},
    }
    row.update(changes)
    return row


def test_numbered_issue_admission_needs_official_exact_title_and_authors():
    paper = program_papers(document(), "CSCW", 2025)[0]
    assert match_hci_publication(paper, [metadata()])["DOI"] == "10.1145/1234567"
    assert match_hci_publication(paper, [metadata(title=["Different Paper"])]) is None
    assert (
        match_hci_publication(
            paper, [metadata(author=[{"given": "Other", "family": "Lee"}])]
        )
        is None
    )
    assert match_hci_publication(paper, [metadata(ISSN=["2475-1421"])]) is None
    assert (
        match_hci_publication(paper, [metadata(), metadata(DOI="10.1145/7654321")])
        is None
    )


def test_draft_program_is_not_publication_evidence():
    data = document()
    data["publicationInfo"] = {"publicationStatus": "DRAFT", "isDraft": True}
    with pytest.raises(ValueError):
        program_papers(data, "CSCW", 2025)


def test_mobilehci_editorial_manuscript_suffix_only_allowed_for_that_program():
    paper = program_papers(document(), "CSCW", 2025)[0]
    paper["conference"] = "MobileHCI"
    registered = metadata(title=["Collaborative Systems MHCI006"])
    assert match_hci_publication(paper, [registered]) is registered
    paper["conference"] = "CSCW"
    assert match_hci_publication(paper, [registered]) is None
    paper["conference"] = "MobileHCI"
    assert (
        match_hci_publication(paper, [metadata(title=["Different Paper MHCI006"])])
        is None
    )
