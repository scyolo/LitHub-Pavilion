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


def test_vis_2023_uses_string_authors_and_the_official_virtual_archive():
    source = row(authors=['Ada Lee', 'Bob Smith'],
                 time_stamp='2023-10-24T03:00:00Z',
                 abstract='An official visualization abstract.')
    record, = parse_vis([source], 2023)
    assert record.authors == ['Lee, Ada', 'Smith, Bob']
    assert record.official_url == 'https://virtual.ieeevis.org/year/2023/paper_v-full-1.html'
    assert record.extra['abstract'] == 'An official visualization abstract.'


def test_hipeac_2023_markdown_doi_links_require_complete_authors_not_drafts():
    from app.collectors.official_conference_lists import parse_hipeac_session

    source = {
        'id': 8050, 'type': {'value': 'Paper Track'},
        'event': {'name': 'HiPEAC 2023'}, 'start_at': '2023-01-16T11:00:00+01:00',
        'description': '- _Efficient architectures_, Ada Lee and Bob Smith '
                       '[[TACO-2022-11](https://dl.acm.org/doi/pdf/10.1145/3566053)]\n'
                       '- _Unpublished draft_, [[TACO draft](https://www.hipeac.net/media/draft.pdf)]',
    }
    records = parse_hipeac_session(source, 2023)
    assert len(records) == 1 and records[0].doi == '10.1145/3566053'
    assert records[0].authors == ['Lee, Ada', 'Smith, Bob']
    assert parse_hipeac_session(source, 2024) == []


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
