import pytest
from app.collectors.acm_open_toc import parse_open_toc

PAGE = """<h1>Research 2025</h1><a href="https://dl.acm.org/doi/proceedings/10.1145/123">Library</a>
<h2>SESSION: Research</h2><h3><a class="DLtitleLink" href="https://dl.acm.org/doi/10.1145/123.456">Exact &amp; Safe</a></h3>
<ul class="DLauthors"><li class="nameList">First Author</li><li class="nameList Last">Second Author</li></ul>"""


def test_open_toc_identity_and_author_order():
    rows = parse_open_toc(PAGE, "10.1145/123", "Research 2025")
    assert rows == [
        {
            "doi": "10.1145/123.456",
            "title": "Exact & Safe",
            "section": "SESSION: Research",
            "authors": ["First Author", "Second Author"],
        }
    ]


@pytest.mark.parametrize(
    "page",
    [
        PAGE.replace("123.456", "999.456"),
        PAGE.replace("Research 2025", "Research 2024"),
        PAGE.split("<ul")[0],
        PAGE.replace('class="nameList"', 'class="other"').replace(
            'class="nameList Last"', 'class="other"'
        ),
    ],
)
def test_open_toc_rejects_unproven_or_truncated_identity(page):
    with pytest.raises(ValueError):
        parse_open_toc(page, "10.1145/123", "Research 2025")


def test_subtitle_join_requires_exact_same_doi_official_title():
    from app.collectors.acm_open_toc import restore_verified_subtitles

    item = {
        "DOI": "10.1145/123.456",
        "title": ["Smartpick"],
        "subtitle": ["Workload Prediction"],
    }
    official = [{"doi": item["DOI"], "title": "Smartpick: Workload Prediction"}]
    result, count = restore_verified_subtitles([item], official)
    assert result[0]["title"] == [official[0]["title"]] and count == 1
    assert item["title"] == ["Smartpick"]
    assert restore_verified_subtitles(
        [item], [{"doi": "10.1145/123.789", "title": official[0]["title"]}]
    ) == ([item], 0)
    assert restore_verified_subtitles(
        [item], [{"doi": item["DOI"], "title": "Smartpick: Different"}]
    ) == ([item], 0)


def test_only_open_toc_region_is_read_not_unrelated_site_footer():
    page = '<div id="DLtoc">' + PAGE + "</div><h3>Unrelated site policy</h3>"
    assert len(parse_open_toc(page, "10.1145/123", "Research 2025")) == 1
