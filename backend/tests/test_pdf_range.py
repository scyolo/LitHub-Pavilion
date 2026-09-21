"""PDF Range 流式接口测试（6.1）：200/206/416/403/路径越界 404。"""
import pytest


@pytest.fixture()
def downloaded_paper(db, sample_paper, tmp_path, monkeypatch):
    from app import config as config_module

    papers_dir = tmp_path / "papers"
    (papers_dir / "NeurIPS" / "2024").mkdir(parents=True)
    pdf = papers_dir / "NeurIPS" / "2024" / "000001_fast-inference-via-spec.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"x" * 4096)
    sample_paper.pdf_status = "downloaded"
    sample_paper.pdf_path = "NeurIPS/2024/000001_fast-inference-via-spec.pdf"
    db.commit()
    monkeypatch.setattr(config_module.settings, "papers_root", papers_dir)
    return sample_paper


def test_full_download(client, downloaded_paper):
    resp = client.get(f"/api/papers/{downloaded_paper.id}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.headers["accept-ranges"] == "bytes"
    assert resp.content.startswith(b"%PDF")


def test_range_request_returns_206(client, downloaded_paper):
    resp = client.get(
        f"/api/papers/{downloaded_paper.id}/pdf", headers={"Range": "bytes=0-1023"}
    )
    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 0-1023/4105"
    assert len(resp.content) == 1024


def test_suffix_range(client, downloaded_paper):
    resp = client.get(
        f"/api/papers/{downloaded_paper.id}/pdf", headers={"Range": "bytes=-100"}
    )
    assert resp.status_code == 206
    assert len(resp.content) == 100
    assert resp.headers["content-range"].endswith("/4105")


def test_invalid_range_returns_416_with_content_range(client, downloaded_paper):
    resp = client.get(
        f"/api/papers/{downloaded_paper.id}/pdf", headers={"Range": "bytes=99999-100000"}
    )
    assert resp.status_code == 416
    assert resp.headers["content-range"] == "bytes */4105"


def test_closed_paper_returns_403_with_links(client, db, sample_paper):
    sample_paper.pdf_status = "closed"
    sample_paper.oa_url = "https://some-repo.example.org/paper.pdf"
    db.commit()
    resp = client.get(f"/api/papers/{sample_paper.id}/pdf")
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "PDF_CLOSED"
    assert body["error"]["official_url"].startswith("https://doi.org/")
    assert body["error"]["oa_url"].endswith(".pdf")


def test_path_traversal_is_404(client, db, downloaded_paper):
    downloaded_paper.pdf_path = "../../etc/passwd"
    db.commit()
    resp = client.get(f"/api/papers/{downloaded_paper.id}/pdf")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PDF_NOT_FOUND"


def test_download_disposition(client, downloaded_paper):
    resp = client.get(f"/api/papers/{downloaded_paper.id}/pdf?download=1")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
