import pytest
from scripts.audit_www2025_schedule import parse_schedule


def test_schedule_only_admits_numbered_research_sessions_and_does_not_claim_authors():
    import html
    page = '<title>WWW 2025</title>'
    body = '<tr><td>Session4 Recsys1</td><td>Room</td><td>Topic: Rec<br>12, Research Title<br>13, Another Title</td></tr>'
    body += '<tr><td>Industry-1</td><td>Room</td><td>14, Industry Title</td></tr>'
    page += '<iframe srcDoc="' + html.escape(body, quote=True) + '"></iframe>'
    result = parse_schedule(page, expected_sessions=1)
    assert [row['submission_id'] for row in result] == ['12', '13']
    assert all('authors' not in row for row in result)
    with pytest.raises(ValueError):
        parse_schedule(page, expected_sessions=32)


def test_journal_presentations_are_not_conference_records_and_duplicate_ids_are_retained_for_review():
    import html
    body = '<tr><td>Session1 Search</td><td>Room</td><td>Topic: Search<br>TWeb2, Journal Paper<br>310, First Title<br>310, Second Title</td></tr>'
    rows = parse_schedule('<iframe srcDoc="' + html.escape(body, quote=True) + '"></iframe>', expected_sessions=1)
    assert len(rows) == 2
    assert [r['submission_id'] for r in rows] == ['310', '310']
    assert all(r['title'] != 'Journal Paper' for r in rows)


def test_posters_require_complete_research_numbering_and_ignore_demo():
    import html
    from scripts.audit_www2025_schedule import parse_posters
    rows = '<tr><td>Research-1</td><td>310</td><td>First title</td></tr><tr><td>Research-2</td><td>311</td><td>Second title</td></tr><tr><td>Demo-1</td><td>900</td><td>Demo title</td></tr>'
    page = '<iframe srcDoc="' + html.escape(rows, quote=True) + '"></iframe>'
    assert len(parse_posters(page, expected_count=2)) == 2
    with pytest.raises(ValueError):
        parse_posters(page, expected_count=408)
    with pytest.raises(ValueError):
        parse_posters(page.replace('Research-2', 'Research-1'), expected_count=2)
