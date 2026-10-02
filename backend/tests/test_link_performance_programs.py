from argparse import Namespace
from pathlib import Path

import pytest

from app.models import Author, PaperAuthor, PaperConference, Venue
from scripts import link_performance_programs as module


@pytest.mark.asyncio
async def test_dry_run_never_persists_nested_association(
    db, sample_paper, session_factory, tmp_path, monkeypatch
):
    sample_paper.title = "Efficient queueing"
    sample_paper.title_norm = "efficient queueing"
    journal = db.get(Venue, sample_paper.venue_id)
    journal.abbr = "Performance Evaluation: An International Journal"
    conf = Venue(
        abbr="Performance", name="Performance", type="conf", ccf_level="B", active=1
    )
    authors = [
        Author(name="Lee, Alice", name_norm="alice lee"),
        Author(name="Smith, Robert", name_norm="robert smith"),
    ]
    db.add_all([conf, *authors])
    db.flush()
    for i, a in enumerate(authors, 1):
        db.add(PaperAuthor(paper_id=sample_paper.id, author_id=a.id, author_order=i))
    db.commit()
    monkeypatch.setattr(
        module,
        "PROGRAMS",
        {2025: "https://performance2025.sciencesconf.org/resource/page/id/3"},
    )
    html = '<title>IFIP WG 7.3 Performance</title><input name="conference" value="performance2025"><p>Session 1 — Queues</p><li>A. Lee, R. Smith - <em>Efficient queueing</em> (paper #1)</li>'
    (tmp_path / "program-2025.html").write_text(html, encoding="utf-8")
    args = Namespace(
        database=Path(session_factory.kw["bind"].url.database),
        output=tmp_path,
        apply=False,
    )
    report = await module.run(args)
    assert report["units"][0]["matched_publications"] == 1
    db.rollback()
    assert db.query(PaperConference).count() == 0
