import hashlib
import json
from pathlib import Path

from app.models import Author, Paper, PaperAuthor
from scripts.reconcile_preprint_evidence import reconcile_cached


def evidence_case(db, tmp_path, venue):
    title = 'Verified scientific publication'
    old = Paper(source='dblp', dblp_key='conf/nips/Old25', title=title, title_norm=title.lower(),
                year=2024, venue_id=venue.id, ccf_level='A', doi='10.48550/arxiv.2401.12345',
                arxiv_id='2401.12345', official_url='https://arxiv.org/abs/2401.12345')
    key = 'https://papers.nips.cc/paper_files/paper/2025/hash/abc-Abstract-Conference.html'
    new = Paper(source='manual', publisher_key=key, title=title, title_norm=title.lower(),
                year=2025, venue_id=venue.id, ccf_level='A', official_url=key)
    author = Author(name='Lovelace, Ada', name_norm='lovelaceada')
    db.add_all([old, new, author]); db.flush()
    db.add(PaperAuthor(paper_id=new.id, author_id=author.id, author_order=1)); db.commit()
    url = 'https://papers.nips.cc/paper_files/paper/2025'
    cache = tmp_path / ('toc-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.txt')
    cache.write_text(f'<li><a href="/paper_files/paper/2025/hash/abc-Abstract-Conference.html">{title}</a><span class="paper-authors">Ada Lovelace</span></li>', encoding='utf-8')
    (tmp_path / 'official-inventory-1.json').write_text(json.dumps({'units': [{'venue': 'NeurIPS', 'year': 2025, 'url': url, 'inventory_complete': True}]}), encoding='utf-8')
    arxiv = tmp_path / 'arxiv.html'
    arxiv.write_text(f'<meta name="citation_arxiv_id" content="2401.12345"><meta name="citation_title" content="{title}"><meta name="citation_author" content="Lovelace, Ada"><meta name="citation_abstract" content="Reliable scientific abstract.">', encoding='utf-8')
    fetched = tmp_path / 'fetched.json'
    fetched.write_text(json.dumps([{'id': old.id, 'cache': str(arxiv)}]), encoding='utf-8')
    return old, new, fetched, arxiv


def test_arxiv_only_corroborates_independent_publisher_evidence(db, engine, sample_venue, tmp_path):
    old, official, fetched, _ = evidence_case(db, tmp_path, sample_venue)
    path = Path(engine.url.database)
    preview = reconcile_cached(path, tmp_path, fetched)
    assert preview['dry_run'] and len(preview['changes']) == 1
    db.expire_all(); assert db.query(Paper).count() == 2
    result = reconcile_cached(path, tmp_path, fetched, apply=True)
    assert result['integrity'] == 'ok'
    db.expire_all()
    paper = db.query(Paper).one()
    assert paper.id == old.id and paper.year == 2025 and paper.arxiv_id == '2401.12345'
    assert paper.abstract == 'Reliable scientific abstract.'
    assert db.query(PaperAuthor).count() == 1


def test_cached_arxiv_identity_mismatch_cannot_change_a_paper(db, engine, sample_venue, tmp_path):
    old, official, fetched, arxiv = evidence_case(db, tmp_path, sample_venue)
    arxiv.write_text(arxiv.read_text('utf-8').replace('2401.12345', '2401.54321'), encoding='utf-8')
    result = reconcile_cached(Path(engine.url.database), tmp_path, fetched, apply=True)
    assert not result['changes'] and len(result['skipped']) == 1
    db.expire_all(); assert db.query(Paper).count() == 2


def test_arxiv_claim_without_official_inventory_is_not_publication_evidence(db, engine, sample_venue, tmp_path):
    old, official, fetched, _ = evidence_case(db, tmp_path, sample_venue)
    (tmp_path / 'official-inventory-1.json').write_text(json.dumps({'units': []}), encoding='utf-8')
    result = reconcile_cached(Path(engine.url.database), tmp_path, fetched)
    assert not result['changes']
