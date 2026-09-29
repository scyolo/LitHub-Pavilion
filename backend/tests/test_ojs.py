import pytest
from app.collectors.ojs import BASES, parse_archive, parse_issue, fetch_ojs_inventory
from app.collectors.editions import publication_schedule


def issue_block(number=1, year=2024):
    return f'<div class="issue-summary"><h2><a class="title" href="{BASES["JAIR"]}issue/view/{number}">Vol. 80 ({year})</a></h2></div>'


def article(title="Structured Knowledge", author="Ada Lovelace", number=1):
    return f'<div class="article-summary"><h3><a href="{BASES["JAIR"]}article/view/{number}">{title}</a></h3><div class="authors">{author}</div></div>'


def test_article_identity_and_frontmatter():
    records = parse_issue(article() + article("Frontmatter", number=2), "JAIR", 2024)
    assert len(records) == 1
    assert records[0].title == "Structured Knowledge"
    assert records[0].year == 2024
    assert records[0].venue_key.endswith("/article/view/1")


@pytest.mark.parametrize("body", [article(author=""), article().replace("/jair/article", "/other/article"), article() + article(), article().replace("/view/1", "/view/1/99")])
def test_invalid_article_fails_closed(body):
    with pytest.raises(ValueError):
        parse_issue(body, "JAIR", 2024)


def test_missing_archive_next_link_fails_closed():
    with pytest.raises(ValueError, match="Incomplete"):
        parse_archive(issue_block() + '<div>1-1 of 2</div>', "JAIR")


@pytest.mark.asyncio
async def test_complete_archive_pagination():
    base = BASES["JAIR"]
    pages = {
        base + "issue/archive": issue_block() + f'<div>1-1 of 2</div><a class="next" href="{base}issue/archive/2">Next</a>',
        base + "issue/archive/2": issue_block(2) + '<div>2-2 of 2</div>',
        base + "issue/view/1": article(),
        base + "issue/view/2": article(number=2),
    }
    visited = []
    async def read(url):
        visited.append(url)
        return pages[url]
    records = await fetch_ojs_inventory(read, "JAIR", 2024)
    assert len(records) == 2
    assert len(visited) == 4


@pytest.mark.asyncio
async def test_repeated_pagination_fails_closed():
    base = BASES["JAIR"]
    async def read(url):
        return issue_block() + f'<a class="next" href="{base}issue/archive/2">Next</a>'
    with pytest.raises(ValueError):
        await fetch_ojs_inventory(read, "JAIR", 2024)


def test_future_publications_remain_retryable():
    assert publication_schedule("NeurIPS", 2026)["status"] == "scheduled"
    assert publication_schedule("EMNLP", 2026)["status"] == "scheduled"
    assert publication_schedule("COLING", 2026)["status"] == "scheduled"
    assert publication_schedule("ICCV", 2024)["status"] == "not_applicable"


def test_issue_year_overrides_stale_copyright():
    body = '<div class="obj_issue_summary"><h2><a class="title" href="https://ojs.aaai.org/index.php/ICAPS/issue/view/663">ICAPS Proceedings</a><div>Vol. 35 (2025)</div></h2><p>Copyright © 2024. ICAPS 2025.</p></div>'
    issues, _, _ = parse_archive(body, "ICAPS")
    assert issues[0]["year"] == 2025
