"""SSRF 校验器测试（6.4）：https-only、白名单、DNS 解析后拒绝私网/保留地址。"""
import pytest

from app.security import PdfUrlRejected, validate_pdf_url

WHITELIST = {"arxiv.org", "export.arxiv.org", "aclanthology.org"}


@pytest.mark.asyncio
async def test_rejects_http_scheme():
    with pytest.raises(PdfUrlRejected):
        await validate_pdf_url("http://arxiv.org/pdf/2401.12345", WHITELIST)


@pytest.mark.asyncio
async def test_rejects_non_whitelist_host():
    with pytest.raises(PdfUrlRejected):
        await validate_pdf_url("https://evil.example.com/paper.pdf", WHITELIST)


@pytest.mark.asyncio
async def test_allows_whitelisted_host(monkeypatch):
    import app.security as sec

    monkeypatch.setattr(sec, "_check_resolved_ips", lambda host: ["93.184.216.34"])
    host = await validate_pdf_url("https://export.arxiv.org/pdf/2401.12345", WHITELIST)
    assert host == "export.arxiv.org"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_ip", ["127.0.0.1", "169.254.169.254", "10.0.0.5", "192.168.1.1", "::1"])
async def test_rejects_private_and_reserved_resolution(monkeypatch, bad_ip):
    import app.security as sec

    monkeypatch.setattr(sec, "_check_resolved_ips", lambda host: (_ for _ in ()).throw(PdfUrlRejected(f"解析到禁止地址 {bad_ip}")))
    with pytest.raises(PdfUrlRejected):
        await validate_pdf_url("https://arxiv.org/pdf/2401.12345", WHITELIST)


@pytest.mark.asyncio
async def test_rejects_localhost_and_empty():
    with pytest.raises(PdfUrlRejected):
        await validate_pdf_url("https://localhost:8000/secret.pdf", WHITELIST)
    with pytest.raises(PdfUrlRejected):
        await validate_pdf_url(None, WHITELIST)


@pytest.mark.parametrize("url", [
    "", "   ", "javascript:alert(1)", "data:text/html,bad", "file:///tmp/paper.pdf",
    "ftp://example.org/paper", "//example.org/paper", "https:///missing-host",
    "https://user:password@example.org/paper", "https://user@example.org/paper",
    "http://localhost/paper", "https://sub.localhost/paper", "http://127.0.0.1/paper",
    "https://sub．localhost/paper", "https://printer．local/paper",
    "http://10.1.2.3/paper", "http://172.16.1.2/paper", "http://192.168.1.1/paper",
    "http://169.254.169.254/latest", "http://[::1]/paper", "https://[fc00::1]/paper",
    "http://[::ffff:127.0.0.1]/paper", "https://127.1/paper", "http://2130706433/paper",
    "http://0x7f000001/paper", "http://%31%32%37.0.0.1/paper",
    "https://example.org\\@127.0.0.1/paper", "https://example.org:bad/paper",
    "https://example.org:99999/paper", "https://example.org/a\nb", "https://example.org/a b",
    "https://example.org/%0d%0aHeader", "https://[invalid]/paper",
])
def test_unsafe_display_links_are_removed_consistently(client, db, sample_paper, url):
    sample_paper.source = "openalex"
    sample_paper.openalex_id = "WDisplaySafety"
    sample_paper.dblp_key = None
    sample_paper.doi = None
    sample_paper.arxiv_id = None
    sample_paper.official_url = url
    sample_paper.oa_url = url
    sample_paper.pdf_status = "closed"
    db.commit()
    cards = [
        client.get("/api/papers").json()["items"][0],
        client.get("/api/search", params={"q": "speculative"}).json()["items"][0],
        client.get(f"/api/papers/{sample_paper.id}").json(),
    ]
    for card in cards:
        assert card["oa_url"] is None
        assert card["official_url"] is None
    dashboard = client.get("/api/stats/dashboard").json()
    assert dashboard["with_oa_link"] == 0
    assert client.get("/api/papers", params={"access": "oa"}).json()["total"] == 0
    assert client.get("/api/search", params={"q": "speculative", "access": "official"}).json()["total"] == 1
    error = client.get(f"/api/papers/{sample_paper.id}/pdf").json()["error"]
    assert error.get("oa_url") is None and error.get("official_url") is None


@pytest.mark.parametrize("raw,expected", [
    ("2401.12345", "https://arxiv.org/abs/2401.12345"),
    ("2401.12345v2", "https://arxiv.org/abs/2401.12345v2"),
    ("arXiv:2401.12345", "https://arxiv.org/abs/2401.12345"),
    ("https://arxiv.org/pdf/2401.12345v2.pdf", "https://arxiv.org/abs/2401.12345v2"),
    ("hep-th/9901001", "https://arxiv.org/abs/hep-th/9901001"),
    ("javascript:alert(1)", None),
    ("2401.12345/../../admin", None),
    ("https://evil.example/arxiv.org/abs/2401.12345", None),
    ("https://user:pass@arxiv.org/abs/2401.12345", None),
    (" ", None),
])
def test_arxiv_fallback_matches_access_and_dashboard(client, db, sample_paper, raw, expected):
    sample_paper.arxiv_id = raw
    sample_paper.oa_url = "javascript:alert(1)"
    db.commit()
    assert client.get("/api/papers").json()["items"][0]["oa_url"] == expected
    assert client.get(f"/api/papers/{sample_paper.id}").json()["oa_url"] == expected
    count = 1 if expected else 0
    assert client.get("/api/search", params={"q": "speculative", "access": "oa"}).json()["total"] == count
    assert client.get("/api/stats/dashboard").json()["with_oa_link"] == count


@pytest.mark.parametrize("doi,official,dblp_key,expected", [
    (" DOI:10.5555/ABC ", "https://publisher.example.org/paper", None, "https://doi.org/10.5555/abc"),
    ("https://doi.org/10.5555/ABC", "", None, "https://doi.org/10.5555/abc"),
    ("http://dx.doi.org/10.5555/ABC", "", None, "https://doi.org/10.5555/abc"),
    ("doi.org/10.5555/ABC", "", None, "https://doi.org/10.5555/abc"),
    ("10.5555/part#one?x", "", None, "https://doi.org/10.5555/part%23one%3Fx"),
    ("not-a-doi", " HTTPS://Publisher.Example.org/paper ", None, "https://publisher.example.org/paper"),
    ("javascript:alert(1)", "", "conf/nips/Test2024", "https://dblp.org/rec/conf/nips/Test2024"),
    (None, "", "conf/../../admin", None),
    (None, "", "javascript:alert(1)", None),
    (None, "https://doi.org/https://doi.org/10.5555/abc", "conf/nips/Test2024", "https://dblp.org/rec/conf/nips/Test2024"),
])
def test_official_link_normalization_and_fallback(client, db, sample_paper, doi, official, dblp_key, expected):
    sample_paper.source = "openalex"
    sample_paper.openalex_id = "WOfficialTest"
    sample_paper.doi = doi
    sample_paper.official_url = official
    sample_paper.dblp_key = dblp_key
    db.commit()
    assert client.get("/api/papers").json()["items"][0]["official_url"] == expected
    assert client.get(f"/api/papers/{sample_paper.id}").json()["official_url"] == expected


@pytest.mark.parametrize("url,expected", [
    (" HTTPS://Repository.Example.org/paper ", "https://repository.example.org/paper"),
    ("http://repository.example.org/paper", "http://repository.example.org/paper"),
    ("https://8.8.8.8/paper", "https://8.8.8.8/paper"),
    ("https://[2606:4700:4700::1111]/paper", "https://[2606:4700:4700::1111]/paper"),
])
def test_safe_existing_oa_url_wins_over_arxiv_fallback(client, db, sample_paper, url, expected):
    sample_paper.oa_url = url
    sample_paper.arxiv_id = "2401.12345"
    db.commit()
    assert client.get("/api/papers").json()["items"][0]["oa_url"] == expected
    assert client.get("/api/stats/dashboard").json()["with_oa_link"] == 1
