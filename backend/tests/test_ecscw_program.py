import pytest

from app.collectors.ecscw_program import parse_journal_program


def test_2023_program_keeps_authors_and_explicit_journal_doi():
    html = '''<title>ECSCW 2023 Journal papers program</title>
    <h5>Collaborative Work</h5><p>Ada Lee, University.<br>Bob Smith, Institute.</p>
    <p><strong>Abstract</strong><br>Verified journal abstract.</p>
    <p><a href="https://link.springer.com/article/10.1007/s10606-023-09442-7">https://link.springer.com/article/10.1007/s10606-023-09442-7</a></p>'''
    row, = parse_journal_program(html, 2023)
    assert row.authors == ['Lee, Ada', 'Smith, Bob']
    assert row.doi == '10.1007/s10606-023-09442-7'
    assert row.extra['abstract'] == 'Verified journal abstract.'
    with pytest.raises(ValueError):
        parse_journal_program(html, 2025)


def test_2025_only_reads_the_journal_section_not_exploratory_programmes():
    html = '''<title>Program - ESCSW 2025</title><div class="entry-content"><h1>Program Breakdown</h1>
    <p><strong>Exploratory Paper</strong></p><p><em>Other Author</em></p>
    <h1>Journal Papers</h1><p><strong>Collaborative Work</strong></p>
    <p><em>Ada Lee, Bob Smith</em></p><p>Journal abstract.</p></div>
    <aside><p><strong>28 February 2025</strong></p></aside>'''
    row, = parse_journal_program(html, 2025)
    assert row.title == 'Collaborative Work' and row.authors == ['Lee, Ada', 'Smith, Bob']
