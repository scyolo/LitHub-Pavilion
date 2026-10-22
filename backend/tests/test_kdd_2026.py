import json
from types import SimpleNamespace

import pytest

from app.collectors.catalog_conferences import conference_year
from app.collectors.kdd import parse_kdd_research


def page(second=None):
    first = [
        {
            "track": "rtp",
            "title": "Fast inference [with verification]",
            "url": "https://doi.org/10.1145/3770854.3780251",
            "authors": "Ada Lovelace (Institute); Alan Turing (Lab)",
        }
    ]
    second = (
        second
        if second is not None
        else [
            {
                "track": "dtb",
                "title": "Language model benchmark",
                "url": "https://doi.org/10.1145/3770855.3817448",
                "authors": "Grace Hopper (University)",
            }
        ]
    )
    return (
        "<title>Papers – KDD 2026</title><script>const cycle1Papers = "
        + json.dumps(first)
        + "; const cycle2Papers = "
        + json.dumps(second)
        + ";</script>"
    )


def test_kdd_2026_reads_both_archival_cycles_as_json_data():
    papers = parse_kdd_research(page(), 2026)
    assert len(papers) == 2
    assert papers[0].year == 2026
    assert papers[0].authors == ["Lovelace, Ada", "Turing, Alan"]
    assert {p.doi for p in papers} == {
        "10.1145/3770854.3780251",
        "10.1145/3770855.3817448",
    }


def test_kdd_display_id_mapping_is_recognized_without_running_javascript():
    html = page().replace("];", "].map((paper, index) => ({ ...paper, id: index }));")
    assert len(parse_kdd_research(html, 2026)) == 2
    with pytest.raises(ValueError):
        parse_kdd_research(html.replace("id: index", 'title: "changed"'), 2026)


def test_identical_official_rows_are_deduplicated_but_conflicting_dois_fail():
    item = {
        "track": "rtp",
        "title": "Repeated official paper",
        "url": "https://doi.org/10.1145/3770855.3817448",
        "authors": "Grace Hopper (University)",
    }
    papers = parse_kdd_research(page([item, item]), 2026)
    assert len(papers) == 2 and papers[1].extra["catalogue_repeat_count"] == 2
    with pytest.raises(ValueError, match="Conflicting"):
        parse_kdd_research(page([item, {**item, "title": "A different paper"}]), 2026)


@pytest.mark.parametrize(
    "change",
    [
        {"track": "workshop"},
        {"url": "https://doi.org/10.1145/3711896.999"},
        {"authors": ""},
    ],
)
def test_kdd_2026_rejects_unknown_tracks_parents_and_missing_authors(change):
    item = {
        "track": "rtp",
        "title": "Language model benchmark",
        "url": "https://doi.org/10.1145/3770855.3817448",
        "authors": "Grace Hopper (University)",
        **change,
    }
    with pytest.raises(ValueError):
        parse_kdd_research(page([item]), 2026)


def test_kdd_volume_suffix_keeps_explicit_event_year_and_main_track_checks():
    venue = SimpleNamespace(
        abbr="SIGKDD",
        name="ACM SIGKDD Conference on Knowledge Discovery and Data Mining",
        type="conf",
        ccf_level="A",
    )
    item = {
        "DOI": "10.1145/3770854.3780251",
        "type": "proceedings-article",
        "container-title": [
            "Proceedings of the 32nd ACM SIGKDD Conference on Knowledge Discovery and Data Mining V.1"
        ],
        "event": {
            "name": "KDD '26: The 32nd ACM SIGKDD Conference on Knowledge Discovery and Data Mining"
        },
    }
    assert conference_year(item, venue) == 2026
    assert (
        conference_year(
            {**item, "container-title": [item["container-title"][0] + " Companion"]},
            venue,
        )
        is None
    )
