"""PMLR link provenance, metadata-only fetching, and non-destructive OA repair."""
from dataclasses import replace
from types import SimpleNamespace
import hashlib
import json

import httpx
import pytest

from app.collectors.publisher_toc import fetch_official_inventory, parse_pmlr
from app.models import Paper
from app.services.publisher_import import apply_records, fill_missing_oa_links


BASE = "https://proceedings.mlr.press/v247/"
PDF = BASE + "paper24/paper24.pdf"


def pmlr_body(pdf=None, *, slug="paper24", detail=None):
    download = f'<a href="{pdf}"><b>Download</b> PDF</a>' if pdf else ""
    return f'''<h1>Conference on Learning Theory</h1>
    <div data-id="1" class="paper featured"><div class="metadata">
      <p class="title">Learning &amp; <em>Theory</em></p>
      <span class="authors">Ada <b>Lovelace</b></span></div>
      <p class="links"><a href="{detail or slug + '.html'}"><span>abs</span></a>{download}</p>
    </div>'''


@pytest.mark.parametrize("href,expected", [
    ("paper24/paper24.pdf", PDF),
    ("/v247/paper24/paper24.pdf", PDF),
    (PDF, PDF),
    ("paper&#50;4/paper24.pdf", PDF),
    ("https://raw.githubusercontent.com/mlresearch/v247/main/assets/paper24/paper24.pdf",
     "https://raw.githubusercontent.com/mlresearch/v247/main/assets/paper24/paper24.pdf"),
])
def test_pmlr_accepts_only_links_published_for_the_same_paper(href, expected):
    raw, = parse_pmlr(pmlr_body(href), 2024, BASE, "COLT")
    assert raw.extra["oa_pdf"] == expected
    assert raw.official_url == BASE + "paper24.html"
    assert raw.title == "Learning & Theory"
    assert raw.authors == ["Lovelace, Ada"]


@pytest.mark.parametrize("href", [
    "https://example.org/paper24.pdf",
    "https://proceedings.mlr.press.evil.example/v247/paper24/paper24.pdf",
    "https://proceedings.mlr.press/v246/paper24/paper24.pdf",
    "https://proceedings.mlr.press/v247/other/other.pdf",
    "https://proceedings.mlr.press/v247/paper24/other.pdf",
    "https://raw.githubusercontent.com/mlresearch/v246/main/assets/paper24/paper24.pdf",
    "https://raw.githubusercontent.com/mlresearch/v247/main/assets/other/other.pdf",
    "https://raw.githubusercontent.com/other/v247/main/assets/paper24/paper24.pdf",
    "https://user@proceedings.mlr.press/v247/paper24/paper24.pdf",
    "http://proceedings.mlr.press/v247/paper24/paper24.pdf",
    "javascript:alert(1)",
    PDF + "?redirect=https://example.org",
    PDF + "#unverified",
])
def test_pmlr_rejects_unverified_pdf_links_without_losing_paper(href):
    raw, = parse_pmlr(pmlr_body(href), 2024, BASE, "COLT")
    assert "oa_pdf" not in raw.extra
    assert raw.official_url == BASE + "paper24.html"


def test_pmlr_does_not_guess_pdf_or_borrow_the_next_papers_link():
    body = pmlr_body() + pmlr_body(BASE + "next24/next24.pdf", slug="next24")
    first, second = parse_pmlr(body, 2024, BASE, "COLT")
    assert "oa_pdf" not in first.extra
    assert second.extra["oa_pdf"] == BASE + "next24/next24.pdf"


@pytest.mark.parametrize("detail", [
    "https://example.org/paper24.html",
    "https://proceedings.mlr.press/v246/paper24.html",
    "../v246/paper24.html",
    "https://proceedings.mlr.press/v247/subdir/paper24.html",
    "paper24.html?redirect=other",
])
def test_pmlr_rejects_an_unverified_abstract_identity(detail):
    with pytest.raises(ValueError, match="verified volume"):
        parse_pmlr(pmlr_body(PDF, detail=detail), 2024, BASE, "COLT")


def test_pmlr_rejects_truncated_paper_blocks():
    with pytest.raises(ValueError, match="incomplete"):
        parse_pmlr(pmlr_body(PDF).rsplit("</div>", 1)[0], 2024, BASE, "COLT")


@pytest.mark.asyncio
async def test_pmlr_fetches_only_index_and_metadata_not_pdfs():
    requests = []

    def handler(request):
        url = str(request.url)
        requests.append(url)
        if url == "https://proceedings.mlr.press/":
            body = '<li><a href="v247">Proceedings of COLT 2024</a></li>'
        else:
            assert url == BASE
            body = pmlr_body(PDF)
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    class Limiter:
        async def acquire(self):
            pass

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        raw, = await fetch_official_inventory(client, Limiter(), SimpleNamespace(abbr="COLT"), 2024)
    assert raw.extra["oa_pdf"] == PDF
    assert requests == ["https://proceedings.mlr.press/", BASE]


def test_oa_repair_only_changes_blank_oa_fields_and_is_idempotent(db, sample_venue):
    original, = parse_pmlr(pmlr_body(), 2024, BASE, "COLT")
    apply_records(db, [original], sample_venue)
    paper = db.query(Paper).one()
    paper.note = "Keep my manual note"
    db.commit()
    before = {column.name: getattr(paper, column.name) for column in Paper.__table__.columns}
    linked, = parse_pmlr(pmlr_body(PDF), 2024, BASE, "COLT")
    result = fill_missing_oa_links(db, [linked], sample_venue)
    assert result["counts"] == {"updated": 1}
    db.refresh(paper)
    assert paper.oa_url == PDF
    for field, value in before.items():
        if field not in ("oa_url", "updated_at"):
            assert getattr(paper, field) == value
    assert fill_missing_oa_links(db, [linked], sample_venue)["counts"] == {"already_linked": 1}
    paper.oa_url = "https://arxiv.org/abs/2401.12345"
    db.commit()
    assert fill_missing_oa_links(db, [linked], sample_venue)["counts"] == {"already_linked": 1}
    assert paper.oa_url == "https://arxiv.org/abs/2401.12345"
    assert db.query(Paper).count() == 1


def test_oa_repair_never_inserts_or_accepts_mismatched_metadata(db, sample_venue):
    raw, = parse_pmlr(pmlr_body(PDF), 2024, BASE, "COLT")
    assert fill_missing_oa_links(db, [raw], sample_venue)["counts"] == {"missing_publication": 1}
    assert db.query(Paper).count() == 0
    original, = parse_pmlr(pmlr_body(), 2024, BASE, "COLT")
    apply_records(db, [original], sample_venue)
    for invalid in [replace(raw, year=2023), replace(raw, title="Unrelated article"), replace(raw, authors=["Turing, Alan"])]:
        result = fill_missing_oa_links(db, [invalid], sample_venue)
        assert result["counts"] == {"identity_conflicts": 1}
    assert db.query(Paper).one().oa_url is None


@pytest.mark.asyncio
async def test_scoped_cached_oa_import_backs_up_and_reports_only_requested_years(db, sample_venue, engine, tmp_path, monkeypatch):
    from scripts import collect_official_inventories as collector

    sample_venue.abbr = "COLT"
    db.commit()
    raw, = parse_pmlr(pmlr_body(), 2024, BASE, "COLT")
    apply_records(db, [raw], sample_venue)
    output = tmp_path / "audit"
    output.mkdir()
    index = '<li><a href="v247">Proceedings of COLT 2024</a></li><li><a href="v244">Proceedings of UAI 2024</a></li>'
    for url, body in [("https://proceedings.mlr.press/", index), (BASE, pmlr_body(PDF))]:
        (output / ("toc-" + hashlib.sha256(url.encode()).hexdigest()[:16] + ".txt")).write_text(body, encoding="utf-8")
    real_client = httpx.AsyncClient

    def reject_network(request):
        raise AssertionError("Cached OA repair must not perform network or PDF requests")

    monkeypatch.setattr(collector.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(reject_network), **kwargs))
    args = SimpleNamespace(database=tmp_path / "test.db", output=output, year_from=2023, year_to=2024,
                           venues=["COLT"], refresh=False, missing_only=False, oa_links_only=True)
    await collector.run(args)
    report = json.loads(next(output.glob("official-inventory-*.json")).read_text(encoding="utf-8"))
    assert report["mode"] == "oa_links_only"
    assert {(unit["venue"], unit["year"]) for unit in report["units"]} == {("COLT", 2023), ("COLT", 2024)}
    assert report["paper_count"] == 1 and report["pdf_downloads"] == 0 and report["quick_check"] == "ok"
    assert len(list((tmp_path / "backups").glob("*.db"))) == 1
    db.expire_all()
    assert db.query(Paper).one().oa_url == PDF
