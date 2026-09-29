import copy
import json
import pytest
from app.collectors.csdl import index_url, articles_url, fetch_csdl_inventory


def issue(number="01", **kw):
    return dict(id="issue-" + number, idPrefix="tp", year="2026", issueNum=number, title="Jan.", isPreviewOnly=False, **kw)


def article(n=1):
    return dict(id=str(n), title="Learning <SEG> with <i>geometry</i>", doi=f"10.1109/TPAMI.2025.{n}", year="2026", issueNum="01", pubDate="2026-01-01", authors=[{"fullName": "Ada Lovelace"}], abstract="Structured learning")


def pages(n=1):
    result = {index_url(2026): json.dumps({"data": {"periodicalIssues": [issue()]}})}
    for skip in range(0, n, 100):
        result[articles_url(2026, "01", skip)] = json.dumps({"data": {"articlesWithPagination": {"skipped": skip, "limit": 100, "totalResults": n, "articleResults": [article(k+1) for k in range(skip, min(skip+100,n))]}}})
    return result


async def collect(data):
    async def read(url):
        return data[url]
    return await fetch_csdl_inventory(read, 2026)


@pytest.mark.asyncio
async def test_complete_pagination_issue_year_and_scientific_title():
    records = await collect(pages(101))
    assert len(records) == 101
    assert records[0].year == 2026
    assert records[0].doi == "10.1109/tpami.2025.1"
    assert records[0].publication_date == "2026-01-01"
    assert records[0].title == "Learning <SEG> with geometry"
    assert records[0].extra["abstract"] == "Structured learning"


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["errors", "truncated", "wrong_year", "duplicate_id", "duplicate_doi", "missing_authors", "wrong_venue", "wrong_skip", "wrong_total", "preview_missing_flag"])
async def test_invalid_inventory_fails_closed(fault):
    data = pages(2)
    address = articles_url(2026, "01", 0)
    body = json.loads(data[address]); page = body["data"]["articlesWithPagination"]
    if fault == "errors": body["errors"] = [{"message": "unavailable"}]
    if fault == "truncated": page["articleResults"].pop()
    if fault == "wrong_year": page["articleResults"][0]["year"] = "2025"
    if fault == "duplicate_id": page["articleResults"][1]["id"] = "1"
    if fault == "duplicate_doi": page["articleResults"][1]["doi"] = page["articleResults"][0]["doi"]
    if fault == "missing_authors": page["articleResults"][0]["authors"] = []
    if fault == "wrong_venue": page["articleResults"][0]["doi"] = "10.1109/OTHER.2025.1"
    if fault == "wrong_skip": page["skipped"] = 1
    if fault == "wrong_total": page["totalResults"] = 3
    if fault == "preview_missing_flag":
        listing = json.loads(data[index_url(2026)])
        del listing["data"]["periodicalIssues"][0]["isPreviewOnly"]
        data[index_url(2026)] = json.dumps(listing)
    data[address] = json.dumps(body)
    with pytest.raises(ValueError):
        await collect(data)


@pytest.mark.asyncio
async def test_preview_and_frontmatter_not_imported():
    data = pages(2)
    preview = copy.deepcopy(issue("02")); preview["isPreviewOnly"] = True
    data[index_url(2026)] = json.dumps({"data": {"periodicalIssues": [issue(), preview]}})
    address = articles_url(2026, "01", 0)
    body = json.loads(data[address])
    body["data"]["articlesWithPagination"]["articleResults"][1].update(title="Frontmatter", doi=None, authors=[])
    data[address] = json.dumps(body)
    assert len(await collect(data)) == 1


@pytest.mark.asyncio
async def test_publisher_classified_announcement_not_a_paper():
    data = pages(2)
    address = articles_url(2026, "01", 0)
    body = json.loads(data[address])
    body["data"]["articlesWithPagination"]["articleResults"][1].update(title="IEEE Quantum Week", contentType="content-announce", authors=[])
    data[address] = json.dumps(body)
    assert len(await collect(data)) == 1


def test_publisher_math_sentinels_and_underlined_acronyms():
    from app.collectors.csdl import csdl_text
    assert csdl_text('M<tex-math>Z_$^{3}$_Z</tex-math>D: <underline>M</underline>ultimodal <SEG>') == 'M$^{3}$D: Multimodal <SEG>'
    assert csdl_text('Z_original_Z') == 'Z_original_Z'


@pytest.mark.asyncio
@pytest.mark.parametrize("part", ["issue", "page", "article", "authors", "title"])
async def test_schema_drift_reports_validation_error(part):
    data = pages()
    address = articles_url(2026, "01", 0)
    body = json.loads(data[address]); page = body["data"]["articlesWithPagination"]
    if part == "issue":
        data[index_url(2026)] = json.dumps({"data": {"periodicalIssues": [None]}})
    if part == "page": body["data"]["articlesWithPagination"] = []
    if part == "article": page["articleResults"][0] = None
    if part == "authors": page["articleResults"][0]["authors"] = [None]
    if part == "title": page["articleResults"][0]["title"] = {}
    data[address] = json.dumps(body)
    with pytest.raises(ValueError):
        await collect(data)
