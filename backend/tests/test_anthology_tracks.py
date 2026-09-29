import json
from pathlib import Path

from app.cleaning import normalize_title
from app.models import Paper, Venue
from scripts.repair_anthology_tracks import repair_existing


def test_findings_year_is_corrected_but_not_main_conference_confirmation(db, engine, tmp_path):
    venue = Venue(abbr='EMNLP', name='EMNLP', dblp_stream='conf/emnlp', type='conf', ccf_level='B')
    db.add(venue); db.flush()
    title = 'Verified Findings Paper'
    paper = Paper(source='dblp', dblp_key='conf/emnlp/Test23', title=title, title_norm=normalize_title(title),
                  venue_id=venue.id, ccf_level='B', year=2026, publication_date='2026-03-01',
                  venue_confirmed=1, doi='10.18653/v1/2023.findings-emnlp.961',
                  official_url='https://doi.org/10.18653/v1/2023.findings-emnlp.961')
    db.add(paper); db.commit()
    cache = tmp_path / 'cache.jsonl'
    cache.write_text(json.dumps({'DOI': paper.doi, 'type': 'proceedings-article', 'title': [title],
                                 'container-title': ['Findings of the Association for Computational Linguistics: EMNLP 2023'],
                                 'published': {'date-parts': [[2023, 12]]}}) + '\n', encoding='utf-8')
    preview = repair_existing(Path(engine.url.database), cache)
    assert preview['year_corrections'] == 1
    db.expire_all(); assert paper.year == 2026
    result = repair_existing(Path(engine.url.database), cache, apply=True)
    db.expire_all()
    assert result['year_corrections'] == 1
    assert paper.year == 2023 and paper.venue_confirmed == 0 and paper.publication_date is None
    assert db.query(Paper).count() == 1
    assert repair_existing(Path(engine.url.database), cache, apply=True)['changes'] == []


def test_short_track_repair_preserves_search_record(db, engine):
    from scripts.repair_ccf_tracks import repair_tracks
    venue = Venue(abbr="ACL", name="ACL", dblp_stream="conf/acl", type="conf", ccf_level="A")
    db.add(venue); db.flush()
    paper = Paper(source="manual", doi="10.18653/v1/2025.acl-short.1", title="A Short Paper",
        title_norm="a short paper", venue_id=venue.id, year=2025, ccf_level="A", venue_confirmed=1,
        official_url="https://aclanthology.org/2025.acl-short.1/")
    db.add(paper); db.commit()
    path = Path(engine.url.database)
    assert len(repair_tracks(path)["changes"]) == 1
    db.expire_all(); assert paper.venue_confirmed == 1
    assert len(repair_tracks(path, apply=True)["changes"]) == 1
    db.expire_all(); assert paper.venue_confirmed == 0 and db.query(Paper).count() == 1
    assert not repair_tracks(path, apply=True)["changes"]


def test_aaai_nonmain_issues_are_not_main_proceedings():
    from types import SimpleNamespace
    from app.collectors.dblp import RawPaper
    from app.services.paper_store import ccf_track_eligible
    venue = SimpleNamespace(abbr="AAAI")
    for volume, issue in [(37, 13), (38, 21), (39, 28), (40, 47), (40, 48)]:
        raw = RawPaper(source="manual", venue_key="doi", title="A paper", year=volume+1986, authors=["Ada Lovelace"], doi=f"10.1609/aaai.v{volume}i{issue}.30567")
        assert not ccf_track_eligible(raw, venue)
        raw.doi = f"10.1609/aaai.v{volume}i1.30567"
        assert ccf_track_eligible(raw, venue)
