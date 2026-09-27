"""Retired PDF API: generic 404s, no file exposure, and untouched user archives."""
import pytest
from sqlalchemy import event

from app.models import Paper

ARCHIVE_BYTES = b"%PDF-1.7\n" + b"user-owned-archive" * 256


@pytest.fixture()
def archived_paper(db, sample_paper, tmp_path):
    archive_root = tmp_path / "historical-papers"
    archive = archive_root / "NeurIPS" / "2024" / "000001_fast-inference.pdf"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(ARCHIVE_BYTES)
    sample_paper.pdf_status = "downloaded"
    sample_paper.pdf_source = "arxiv"
    sample_paper.pdf_path = archive.relative_to(archive_root).as_posix()
    db.commit()
    return sample_paper, archive


def test_pdf_route_is_not_advertised(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/papers/{paper_id}/pdf" not in paths
    assert "/api/papers/{paper_id}" in paths


@pytest.mark.parametrize("headers,params", [
    ({}, {}),
    ({"Range": "bytes=0-1023"}, {}),
    ({"Range": "bytes=-100"}, {}),
    ({"Range": "bytes=99999-100000"}, {}),
    ({}, {"download": "1"}),
])
def test_retired_pdf_requests_do_not_read_or_change_archives(client, db, engine, archived_paper, headers, params):
    paper, archive = archived_paper
    before = (paper.pdf_status, paper.pdf_source, paper.pdf_path, paper.updated_at)
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/papers/{paper.id}/pdf", headers=headers, params=params)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.headers["content-type"].startswith("application/json")
    assert not {"accept-ranges", "content-range", "content-disposition"} & response.headers.keys()
    assert statements == []
    db.refresh(paper)
    assert (paper.pdf_status, paper.pdf_source, paper.pdf_path, paper.updated_at) == before
    assert archive.read_bytes() == ARCHIVE_BYTES


@pytest.mark.parametrize("pdf_status", ["pending", "failed", "closed"])
def test_retired_pdf_route_does_not_branch_on_historical_status(client, db, archived_paper, pdf_status):
    paper, archive = archived_paper
    paper.pdf_status = pdf_status
    db.commit()
    response = client.get(f"/api/papers/{paper.id}/pdf")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    db.refresh(paper)
    assert paper.pdf_status == pdf_status
    assert paper.pdf_source == "arxiv"
    assert paper.pdf_path == "NeurIPS/2024/000001_fast-inference.pdf"
    assert archive.read_bytes() == ARCHIVE_BYTES


@pytest.mark.parametrize("paper_id", [999999, "invalid"])
def test_retired_pdf_route_does_not_validate_or_look_up_paper_ids(client, paper_id):
    response = client.get(f"/api/papers/{paper_id}/pdf")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("doi,official,oa,arxiv_id,expected_official,expected_oa", [
    (
        " DOI:10.5555/ABC ", "javascript:alert(1)", "http://127.0.0.1/private.pdf", "2401.12345",
        "https://doi.org/10.5555/abc", "https://arxiv.org/abs/2401.12345",
    ),
    (
        None, "https://user:password@publisher.example.org/paper", "file:///tmp/private.pdf", None,
        "https://dblp.org/rec/conf/nips/test2024fast", None,
    ),
    (
        None, " HTTPS://Publisher.Example.org/paper ", "https://repository.example.org/paper.pdf", "2401.12345",
        "https://publisher.example.org/paper", "https://repository.example.org/paper.pdf",
    ),
])
def test_archived_metadata_keeps_sanitized_source_links_without_file_exposure(
    client, db, archived_paper, doi, official, oa, arxiv_id, expected_official, expected_oa,
):
    paper, archive = archived_paper
    paper.doi, paper.official_url, paper.oa_url, paper.arxiv_id = doi, official, oa, arxiv_id
    db.commit()
    cards = [
        client.get("/api/papers").json()["items"][0],
        client.get("/api/search", params={"q": "speculative"}).json()["items"][0],
        client.get(f"/api/papers/{paper.id}").json(),
    ]
    for card in cards:
        assert card["pdf_status"] == "downloaded"
        assert card["pdf_source"] == "arxiv"
        assert "pdf_url" not in card
        assert "pdf_path" not in card
        assert card["official_url"] == expected_official
        assert card["oa_url"] == expected_oa
    assert cards[-1]["mode"] == "links"
    count = int(expected_oa is not None)
    assert client.get("/api/papers", params={"access": "oa"}).json()["total"] == count
    assert client.get("/api/search", params={"q": "speculative", "access": "official"}).json()["total"] == 1 - count
    assert client.get("/api/stats/dashboard").json()["with_oa_link"] == count
    db.refresh(paper)
    assert (paper.doi, paper.official_url, paper.oa_url, paper.arxiv_id) == (doi, official, oa, arxiv_id)
    assert (paper.pdf_status, paper.pdf_source, paper.pdf_path) == (
        "downloaded", "arxiv", "NeurIPS/2024/000001_fast-inference.pdf",
    )
    assert archive.read_bytes() == ARCHIVE_BYTES


def test_metadata_deletion_keeps_archived_and_unreferenced_files(client, db, archived_paper):
    paper, archive = archived_paper
    other_archive = archive.with_name("unreferenced.pdf")
    other_archive.write_bytes(b"another user archive")
    paper_id = paper.id

    response = client.delete(f"/api/papers/{paper_id}")
    assert response.status_code == 204
    db.expire_all()
    assert db.get(Paper, paper_id) is None
    assert client.get(f"/api/papers/{paper_id}").status_code == 404
    assert client.get(f"/api/papers/{paper_id}/pdf").status_code == 404
    assert archive.read_bytes() == ARCHIVE_BYTES
    assert other_archive.read_bytes() == b"another user archive"
