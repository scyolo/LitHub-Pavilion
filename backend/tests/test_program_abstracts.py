import pytest

from app.collectors.dblp import RawPaper
from app.models import Paper, Venue
from app.services.paper_store import upsert_paper
from app.services.program_abstracts import fill_program_abstracts, program_abstracts


def program_row(**changes):
    row = {
        "sourceurl": "https://openreview.net/group?id=ICML.cc/2024/Conference",
        "eventtype": "Poster",
        "decision": "Accept (Poster)",
        "paper_url": "https://openreview.net/forum?id=VerifiedPaper",
        "name": "Fast decoding",
        "authors": [{"fullname": "Ada Lovelace"}],
        "abstract": "We accelerate language model inference through draft and verification. "
        * 3,
    }
    row.update(changes)
    return row


def test_program_requires_complete_catalog_and_excludes_workshops_or_rejections():
    rows = [
        program_row(),
        program_row(sourceurl="https://openreview.net/group?id=ICML.cc/2024/Workshop"),
        program_row(decision="Reject"),
        program_row(eventtype="Oral"),
        program_row(paper_url="https://openreview.net/forum?id=../private"),
    ]
    records = program_abstracts(
        {"count": len(rows), "results": rows, "next": None}, "ICML", 2024
    )
    assert len(records) == 1 and records[0].title == "Fast decoding"
    with pytest.raises(ValueError, match="Incomplete"):
        program_abstracts({"count": 10, "results": rows}, "ICML", 2024)


def test_neurips_main_program_abstracts_are_supported_without_admitting_new_records():
    row = program_row(
        sourceurl="https://openreview.net/group?id=NeurIPS.cc/2025/Conference"
    )
    assert len(program_abstracts({"count": 1, "results": [row]}, "NeurIPS", 2025)) == 1


def test_enrichment_preserves_metadata_notes_and_nonempty_abstracts(db):
    venue = Venue(
        abbr="ICML",
        name="International Conference on Machine Learning",
        type="conf",
        ccf_level="A",
    )
    db.add(venue)
    db.commit()
    raw = RawPaper(
        source="manual",
        venue_key="https://proceedings.mlr.press/v235/example.html",
        title="Fast decoding",
        year=2024,
        authors=["Lovelace, Ada"],
        official_url="https://proceedings.mlr.press/v235/example.html",
        extra={
            "publisher_key": "https://proceedings.mlr.press/v235/example.html",
            "provenance": "publisher_toc",
        },
    )
    paper, _ = upsert_paper(db, raw, venue)
    paper.note = "My note"
    db.commit()
    (record,) = program_abstracts(
        {"count": 1, "results": [program_row()]}, "ICML", 2024
    )
    assert fill_program_abstracts(db, venue, 2024, [record], "https://icml.cc/program")[
        "filled"
    ] == [paper.id]
    assert (
        db.query(Paper).count() == 1
        and paper.publisher_key == raw.extra["publisher_key"]
    )
    assert paper.note.startswith("My note")
    paper.abstract = "User supplied abstract"
    assert (
        fill_program_abstracts(db, venue, 2024, [record], "https://icml.cc/program")[
            "filled"
        ]
        == []
    )
    assert paper.abstract == "User supplied abstract"
    paper.abstract = None
    record.authors = ["Turing, Alan"]
    assert (
        fill_program_abstracts(db, venue, 2024, [record], "https://icml.cc/program")[
            "filled"
        ]
        == []
    )
    assert paper.abstract is None
    # Publisher issue records can supply a DOI; matching text must not bypass
    # a conflicting publication identity.
    record.authors = ['Ada Lovelace']
    paper.doi = '10.1145/1001'
    record.doi = '10.1145/1002'
    assert not fill_program_abstracts(db, venue, 2024, [record], 'https://icml.cc/program')['filled']
    assert paper.abstract is None
    record.doi = paper.doi
    assert fill_program_abstracts(db, venue, 2024, [record], 'https://icml.cc/program')['filled'] == [paper.id]


def test_official_virtual_pages_and_neurips_host_migration_are_valid_evidence():
    row = program_row(paper_url="", virtualsite_url="/virtual/2024/poster/34602")
    parsed = program_abstracts({"count": 1, "results": [row]}, "ICML", 2024)
    assert parsed[0].official_url == "https://icml.cc/virtual/2024/poster/34602"
    row["virtualsite_url"] = "/virtual/2023/poster/34602"
    assert not program_abstracts({"count": 1, "results": [row]}, "ICML", 2024)
    row = program_row(
        sourceurl="https://openreview.net/group?id=NeurIPS.cc/2023/Conference",
        paper_url="https://proceedings.neurips.cc/paper_files/paper/2023/hash/test-Abstract-Conference.html",
    )
    assert len(program_abstracts({"count": 1, "results": [row]}, "NeurIPS", 2023)) == 1


@pytest.mark.parametrize("venue,year,source,decision", [
    ("CVPR", 2023, "https://openreview.net/group?id=thecvf.com/CVPR/2023/Conference", "Accept"),
    ("CVPR", 2024, "https://openreview.net/group?id=thecvf.com/CVPR/2024/Conference", "Accept: Poster"),
    ("CVPR", 2025, "https://openreview.net/group?id=thecvf.com/CVPR/2025/Conference", None),
    ("ICCV", 2025, "thecvf.com/ICCV/2025/Conference", "highlight"),
])
def test_cvf_program_formats_only_enrich_verified_main_conference_papers(venue, year, source, decision):
    row = program_row(sourceurl=source, decision=decision, paper_url="",
                      virtualsite_url=f"/virtual/{year}/poster/1234")
    records = program_abstracts({"count": 1, "results": [row]}, venue, year)
    assert len(records) == 1
    assert records[0].official_url == f"https://{venue.lower()}.thecvf.com/virtual/{year}/poster/1234"
    for changes in [
        {"sourceurl": source.replace("Conference", "Workshop")},
        {"decision": "Reject"},
        {"eventtype": "Oral"},
        {"virtualsite_url": f"/virtual/{year - 1}/poster/1234"},
        {"abstract": None},
    ]:
        assert not program_abstracts({"count": 1, "results": [row | changes]}, venue, year)
    with pytest.raises(ValueError, match="Incomplete"):
        program_abstracts({"count": 2, "next": "https://example.com/next", "results": [row]}, venue, year)
