from app.collectors.official_conference_lists import parse_vis


def row(**changes):
    data = {
        "id": "v-full-1",
        "title": "Visualization research",
        "authors": [{"name": "Ada Lee"}],
        "doi": "10.1109/TVCG.2024.1",
        "paper_type": "full",
        "event_title": "VIS Full Papers",
        "time_stamp": "2024-10-15T16:10:00Z",
    }
    data.update(changes)
    return data


def test_vis_official_list_excludes_workshops_and_invited_partnerships():
    rows = parse_vis(
        [
            row(),
            row(paper_type="short"),
            row(event_title="CG&A Invited Partnership Presentations"),
            row(time_stamp="2023-10-15T16:10:00Z"),
        ],
        2024,
    )
    assert len(rows) == 1 and rows[0].doi == "10.1109/tvcg.2024.1"
    assert rows[0].extra["provenance"] == "official_conference_list"


def test_ismb_published_proceedings_list_preserves_author_names_only():
    from app.collectors.official_conference_lists import parse_ismb

    html = '<h1>Proceedings Track Presentations</h1><div class="well well-sm"><strong>Protein models</strong></div><ul><li>Ada Lee, University, Country</li><li><span>Bob Smith,</span> Laboratory</li></ul>'
    rows = parse_ismb(html, 2024)
    assert rows[0].title == "Protein models" and rows[0].authors == [
        "Lee, Ada",
        "Smith, Bob",
    ]
    assert rows[0].extra["provenance"] == "official_conference_list"


def test_hipeac_only_explicit_paper_track_and_event_year():
    from app.collectors.official_conference_lists import parse_hipeac_session

    data = {
        "id": 8136,
        "type": {"value": "Paper Track"},
        "event": {"name": "HiPEAC 2024"},
        "start_at": "2024-01-17T11:30:00+01:00",
        "description": "- _Efficient architectures._ Ada Lee and Bob Smith. <https://dl.acm.org/doi/10.1145/3632950>",
    }
    rows = parse_hipeac_session(data, 2024)
    assert len(rows) == 1 and rows[0].doi == "10.1145/3632950"
    data["type"]["value"] = "Workshop"
    assert parse_hipeac_session(data, 2024) == []
