import pytest

from app.collectors.performance_program import parse_program


def document():
    return '<title>IFIP WG 7.3 Performance - Sciencesconf.org</title><input name="conference" value="performance2025"><p><strong>Session 1 — Queueing systems</strong></p><ul><li>A. Lee, B. Smith - <em>Efficient queueing</em> (paper #12)</li><li>N. Charlet, B. Van Houdt - <em>γ</em><em>-CounterBoost</em> (paper #24)</li></ul><p><strong>Session 2 — Scheduling (short papers)</strong></p><ul><li>B. Smith - <em>Short paper</em> (paper #3)</li></ul>'


def test_program_joins_title_fragments_and_excludes_short_sessions():
    records, evidence = parse_program(document(), 2025)
    assert [r.title for r in records] == ["Efficient queueing", "γ-CounterBoost"]
    assert records[0].authors == ["Lee, A.", "Smith, B."]
    assert evidence["long_papers"] == 2 and evidence["short_papers"] == 1
    assert records[0].extra["provenance"] == "official_conference_list"


def test_wrong_edition_and_duplicate_identity_fail_closed():
    with pytest.raises(ValueError):
        parse_program(document(), 2024)
    with pytest.raises(ValueError):
        parse_program(document().replace("(paper #24)", "(paper #12)"), 2025)


def test_2023_program_requires_known_edition_and_explicit_title_author_break():
    doc = '<title>IFIP WG 7.3 Performance 2023 - Sciencesconf.org</title><input name="conference" value="performance2023"><div id="page"><p>KEYNOTE - Another Speaker</p><ul><li><p>Queueing models<br><strong>Alice Lee</strong>, Robert Smith</p></li></ul></div>'
    rows, _stats = parse_program(doc, 2023)
    assert len(rows) == 1 and rows[0].title == "Queueing models"
    assert rows[0].authors == ["Lee, Alice", "Smith, Robert"]
    with pytest.raises(ValueError):
        parse_program(doc.replace("<br>", ""), 2023)
