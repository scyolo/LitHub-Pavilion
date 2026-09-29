import pytest
from app.collectors.publisher_toc import parse_cvf, parse_neurips, parse_anthology, parse_ijcai, parse_kr, pmlr_volumes
from app.collectors.dblp import RawPaper
from app.services.paper_store import upsert_paper
from app.models import Paper
from scripts.collect_official_inventories import apply_records


def test_pmlr_volume_discovery_excludes_workshops():
    body = '<li><a href="v235">Volume 235</a> Proceedings of ICML 2024</li><li><a href="v251">Volume 251</a> Proceedings of GRaM at ICML 2024</li>'
    assert pmlr_volumes(body, [2024]) == [('ICML', 2024, 'https://proceedings.mlr.press/v235/')]


def test_ijcai_official_details_are_the_publication_identity():
    body = """<div id=\"paper1\" class=\"paper_wrapper\"><div class=\"title\">Reasoning &amp; Planning</div><div class=\"authors\">Ada Lovelace, Alan Turing</div><div class=\"details\">(<a href=\"0001.pdf\">PDF</a> | <a href=\"/proceedings/2024/1\"> Details</a>)</div></div>
    <div id=\"paper2\" class=\"paper_wrapper\"><div class=\"title\">Verified Search</div><div class=\"authors\">Grace Hopper</div><div class=\"details\">(<a href=\"0002.pdf\">PDF</a> | <a href=\"/proceedings/2024/2\"> Details</a>)</div></div>"""
    records = parse_ijcai(body, 2024)
    assert [r.extra['publisher_key'] for r in records] == [
        'https://www.ijcai.org/proceedings/2024/1',
        'https://www.ijcai.org/proceedings/2024/2',
    ]
    assert records[0].title == 'Reasoning & Planning'
    assert records[0].authors == ['Lovelace, Ada', 'Turing, Alan']
    with pytest.raises(ValueError):
        parse_ijcai(body.replace('/proceedings/2024/2', '/proceedings/2023/2'), 2024)


def test_kr_official_index_excludes_preface_and_pdf_links():
    body = """<li><div class=\"track_paperinfo__x\"><a href=\"/2024/kr2024-preface.pdf\">Proceedings Preface</a></div></li>
    <li><div class=\"track_paperinfo__x\"><a href=\"/2024/1/\">A KR Paper</a>. <ol class=\"track_authors__x\"><li>Ada Lovelace</li><li>Alan Turing</li></ol></div><div class=\"track_buttons__x\"><a href=\"/2024/1/\">Details</a><a href=\"/2024/1/kr2024-paper.pdf\">PDF</a></div></li>"""
    records = parse_kr(body, 2024)
    assert len(records) == 1
    assert records[0].extra['publisher_key'] == 'https://proceedings.kr.org/2024/1/'
    assert records[0].authors == ['Lovelace, Ada', 'Turing, Alan']
    with pytest.raises(ValueError):
        parse_kr(body.replace('/2024/1/', '/2023/1/'), 2024)


def test_cvf_author_arxiv_and_title_html():
    body = '<dt class="ptitle"><a href="/content/CVPR2023/html/a.html">Fast &amp; Fair</a></dt><dd><input name="query_author" value="Ada Lovelace"><a href="http://arxiv.org/abs/2212.01234">arxiv</a></dd>'
    paper, = parse_cvf(body, 2023, 'CVPR')
    assert paper.title == 'Fast & Fair' and paper.arxiv_id == '2212.01234'
    assert paper.authors == ['Lovelace, Ada']
    assert paper.extra['publisher_key'].endswith('/content/CVPR2023/html/a.html')
    with pytest.raises(ValueError):
        parse_cvf(body, 2023, 'ICCV')


def test_incomplete_official_parser_fails_closed():
    body = '<li><a href="/paper_files/paper/2023/hash/abc-Abstract-Conference.html">A title</a></li>'
    with pytest.raises(ValueError, match='incomplete'):
        parse_neurips(body, 2023)
    with pytest.raises(ValueError):
        parse_cvf('<h1>Challenge page</h1>', 2023, 'CVPR')


def test_doi_optional_official_identity_is_idempotent(db, sample_venue):
    raw = RawPaper(source='manual', venue_key='https://papers.nips.cc/paper/official', title='A real publication', year=2024, authors=['Lovelace, Ada'], official_url='https://papers.nips.cc/paper/official', extra={'publisher_key':'https://papers.nips.cc/paper/official','provenance':'publisher_toc'})
    first = apply_records(db, [raw], sample_venue)
    second = apply_records(db, [raw], sample_venue)
    assert first['counts']['new'] == 1 and second['counts']['updated'] == 1
    p = db.query(Paper).one()
    assert p.doi is None and p.dblp_key is None and p.publisher_key == raw.venue_key
    assert p.venue_confirmed == 1


def test_verified_official_authors_repair_preprint_year_without_losing_arxiv(db, sample_venue):
    preprint = RawPaper(source='openalex', venue_key='W1234', title='A real publication', year=2023, authors=['Lovelace, Ada'], doi='10.48550/arxiv.2301.12345')
    old, _ = upsert_paper(db, preprint, sample_venue); db.commit()
    raw = RawPaper(source='manual', venue_key='https://papers.nips.cc/paper/official', title=old.title, year=2024, authors=['Lovelace, Ada'], official_url='https://papers.nips.cc/paper/official', extra={'publisher_key':'https://papers.nips.cc/paper/official','provenance':'publisher_toc'})
    stats = apply_records(db, [raw], sample_venue)
    assert stats['counts']['years_corrected'] == 1
    assert db.query(Paper).count() == 1 and old.year == 2024
    assert old.arxiv_id == '2301.12345'


def test_same_title_different_authors_are_not_merged_by_official_import(db, sample_venue):
    first = RawPaper(source='dblp', venue_key='conf/nips/First24', title='Same Title', year=2024, authors=['Smith, John'])
    old, _ = upsert_paper(db, first, sample_venue); db.commit()
    official = RawPaper(source='manual', venue_key='https://papers.nips.cc/paper/official', title=old.title, year=2024, authors=['Lovelace, Ada'], official_url='https://papers.nips.cc/paper/official', extra={'publisher_key':'https://papers.nips.cc/paper/official','provenance':'publisher_toc'})
    assert apply_records(db, [official], sample_venue)['counts']['new'] == 1
    assert db.query(Paper).count() == 2


def test_aamas_year_specific_anchors_and_affiliations():
    from app.collectors.publisher_toc import parse_aamas
    body = '''<a name="1" id="1"></a><strong>Keynote Talks</strong>
      <p><a href="../pdfs/p1.pdf">Invited</a><br>Ada Lovelace<i> (Lab)</i></p>
      <a name="2" id="2"></a><strong>Research Paper Track</strong>
      <p><a href="../pdfs/ABCD1234.pdf">Multi-Agent Learning</a><br>Ada Lovelace<i> (Lab, USA)</i><br>Alan Turing<i> (Lab)</i></p>
      <a name="5" id="5"></a><strong>Doctoral Consortium</strong>
      <p><a href="../pdfs/p90.pdf">Thesis</a><br>Ada Lovelace</p>
      <a name="7" id="7"></a><strong>JAAMAS Track</strong>
      <p><a href="../pdfs/p99.pdf">Journal summary</a><br>Ada Lovelace</p>'''
    raw, = parse_aamas(body, 2026)
    assert raw.title == 'Multi-Agent Learning'
    assert raw.authors == ['Lovelace, Ada', 'Turing, Alan']
    assert raw.extra['publisher_key'].endswith('/aamas2026/pdfs/ABCD1234.pdf')


def test_eccv_unquoted_links_and_formal_doi():
    from app.collectors.publisher_toc import parse_eccv
    raw, = parse_eccv('''<dt class="ptitle"><a href=papers/eccv_2024/papers_ECCV/html/4_ECCV_2024_paper.php>Vision</a></dt>
      <dd>Ada Lovelace*, Alan Turing*</dd><a href="https://link.springer.com/chapter/10.1007/978-1_1">doi</a>''', 2024)
    assert raw.doi == '10.1007/978-1_1'
    assert raw.authors == ['Lovelace, Ada', 'Turing, Alan']


def test_neurips_volume_discovery_is_main_only():
    from app.collectors.publisher_toc import neurips_main_volumes
    assert neurips_main_volumes('''<a href="/paper_files/paper/2025/vol38-main-conference">main</a>
      <a href="/paper_files/paper/2025/vol38-workshop">workshop</a>''', 2025) == ['https://papers.nips.cc/paper_files/paper/2025/vol38-main-conference']


def test_lrec_coling_joint_volume_not_unrelated_lrec():
    text = '''<collection id="2024.lrec"><volume id="main"><meta><year>2024</year><venue>lrec</venue></meta>
      <paper id="1"><title>Language resources</title><author><first>Ada</first><last>Lovelace</last></author></paper></volume></collection>'''
    raw, = parse_anthology(text, 2024, 'COLING', '2024.lrec')
    assert raw.extra['publisher_key'] == 'https://aclanthology.org/2024.lrec-main.1/'
    with pytest.raises(ValueError):
        parse_anthology(text, 2024, 'COLING', '2024.coling')




def test_iclr_main_publications_exclude_blogs_journal_track_and_repeat_talks():
    import json
    from app.collectors.publisher_toc import parse_iclr
    poster = {'id': 1, 'name': 'Learning', 'authors': [{'fullname': 'Ada Lovelace'}], 'eventtype': 'Poster', 'decision': 'Accept (Poster)', 'sourceurl': 'https://openreview.net/group?id=ICLR.cc/2025/Conference', 'paper_url': 'https://openreview.net/forum?id=REAL_ID'}
    oral = dict(poster, id=2, eventtype='Oral', paper_url='https://openreview.net/forum?id=SYNTHETIC_ORAL', related_events_ids=[1])
    blog = dict(poster, id=3, sourceurl='https://openreview.net/group?id=ICLR.cc/2025/BlogPosts')
    journal = dict(poster, id=4, sourceurl='TMLR-2024')
    data = {'count': 4, 'next': None, 'results': [poster, oral, blog, journal]}
    raw, = parse_iclr(json.dumps(data), 2025)
    assert raw.extra['publisher_key'] == poster['paper_url']
    oral['related_events_ids'] = [999]
    with pytest.raises(ValueError, match='no verified'):
        parse_iclr(json.dumps(data), 2025)
    oral['related_events_ids'] = [1]
    data['next'] = 'page2'
    with pytest.raises(ValueError, match='Incomplete'):
        parse_iclr(json.dumps(data), 2025)


def test_shared_arxiv_does_not_hide_distinct_formal_publications(db, sample_venue):
    from app.models import Venue
    journal = Venue(abbr='TPAMI', name='TPAMI', dblp_stream='journals/pami', type='journal', ccf_level='A', active=1)
    db.add(journal); db.commit()
    old, _ = upsert_paper(db, RawPaper(source='openalex', venue_key='W99', title='Journal extension', year=2025, authors=['Lovelace, Ada'], doi='10.1234/journal', arxiv_id='2301.12345'), journal)
    db.commit()
    raw = RawPaper(source='manual', venue_key='https://publisher.example/conf/paper', title='Conference paper', year=2023, authors=['Lovelace, Ada'], arxiv_id='2301.12345', official_url='https://publisher.example/conf/paper', extra={'publisher_key': 'https://publisher.example/conf/paper', 'provenance': 'publisher_toc'})
    result = apply_records(db, [raw], sample_venue)
    assert result['counts']['new'] == 1 and result['counts']['shared_preprint_links'] == 1
    new = db.query(Paper).filter(Paper.publisher_key == raw.venue_key).one()
    assert new.id != old.id and new.arxiv_id is None
    assert new.oa_url == 'https://arxiv.org/abs/2301.12345'
    assert old.year == 2025 and old.doi == '10.1234/journal'
    assert apply_records(db, [raw], sample_venue)['counts']['updated'] == 1
    assert db.query(Paper).count() == 2


def test_conflicting_catalogue_doi_does_not_drop_official_article(db, sample_venue):
    def raw(key, title):
        return RawPaper(source='manual', venue_key=key, title=title, year=2024, authors=['Lovelace, Ada'], doi='10.1234/same', official_url=key, extra={'publisher_key': key, 'provenance': 'publisher_toc'})
    apply_records(db, [raw('https://publisher.example/one', 'Image Recognition')], sample_venue)
    result = apply_records(db, [raw('https://publisher.example/two', 'Reinforcement Learning')], sample_venue)
    assert result['counts']['association_conflicts'] == 1
    assert db.query(Paper).count() == 2
    second = db.query(Paper).filter(Paper.publisher_key == 'https://publisher.example/two').one()
    assert second.doi is None and 'Unresolved DOI' in second.note


@pytest.mark.asyncio
async def test_pipeline_official_inventory_precedes_secondary_indexes(db, session_factory, sample_venue, monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.pipeline import CrawlPipeline
    raw = RawPaper(source='manual', venue_key='https://publisher.example/item', title='Official article', year=2024, authors=['Lovelace, Ada'], extra={'publisher_key': 'https://publisher.example/item', 'provenance': 'publisher_toc'})
    official = AsyncMock(return_value=[raw])
    secondary = AsyncMock(side_effect=AssertionError('Secondary source must not be used'))
    monkeypatch.setattr('app.services.pipeline.fetch_official_inventory', official)
    monkeypatch.setattr('app.services.pipeline.fetch_works_by_source', secondary)
    pipeline = CrawlPipeline(session_factory)
    papers, partial = await pipeline._collect_unit_async(db, sample_venue, 2024, False)
    assert not partial and papers == [raw]
    assert pipeline._ingest_batch_sync(db, papers, sample_venue, 2024)[1] == 1
    assert db.query(Paper).one().official_url == raw.extra['publisher_key']
    assert raw.official_url is None  # do not mutate caller-owned inventory metadata


@pytest.mark.asyncio
async def test_pipeline_conflict_is_partial_and_logs_year(db, session_factory, sample_venue, monkeypatch):
    from unittest.mock import AsyncMock
    from app.models import CrawlLog, CrawlState
    from app.collectors.dblp import ProbeResult
    from app.services.pipeline import CrawlPipeline
    key = 'https://publisher.example/item'
    raw = RawPaper(source='manual', venue_key=key, title='Official article', year=2024, authors=['Lovelace, Ada'], extra={'publisher_key': key, 'provenance': 'publisher_toc'})
    apply_records(db, [raw], sample_venue)
    bad = RawPaper(source='manual', venue_key=key, title='A completely unrelated document', year=2024, authors=['Turing, Alan'], extra={'publisher_key': key, 'provenance': 'publisher_toc'})
    pipeline = CrawlPipeline(session_factory)
    monkeypatch.setattr(pipeline, '_probe', AsyncMock(return_value=ProbeResult(False, 'offline')))
    monkeypatch.setattr('app.services.pipeline.fetch_official_inventory', AsyncMock(return_value=[bad]))
    monkeypatch.setattr('app.services.pipeline.enrich_papers', AsyncMock(return_value={'enriched': 0, 'failed': 0}))
    assert await pipeline.submit_backfill(years=[2024], run_id='official-conflict')
    await pipeline.wait_idle()
    db.expire_all()
    unit = db.query(CrawlLog).filter(CrawlLog.venue_id == sample_venue.id).one()
    assert unit.year == 2024 and unit.status == 'partial'
    assert db.query(CrawlState).count() == 0


def test_official_import_rejects_missing_or_unsafe_identity(db, sample_venue):
    for key in (None, 'javascript:alert(1)'):
        raw = RawPaper(source='manual', venue_key='invalid', title='Unsafe identity', year=2024,
                       extra={'publisher_key': key, 'provenance': 'publisher_toc'})
        result = apply_records(db, [raw], sample_venue)
        assert result['counts']['identity_conflicts'] == 1
    assert db.query(Paper).count() == 0


def test_icml_official_catalogue_includes_peer_reviewed_position_track_only():
    import json
    from datetime import datetime, timezone
    from app.collectors.publisher_toc import parse_icml
    poster = {'id': 1, 'name': 'Learning', 'authors': [{'fullname': 'Ada Lovelace'}],
              'eventtype': 'Poster', 'decision': 'Accept (regular)',
              'sourceurl': 'https://openreview.net/group?id=ICML.cc/2026/Conference',
              'paper_url': 'https://openreview.net/forum?id=ICML_MAIN',
              'endtime': '2026-07-09T02:45:00-07:00'}
    oral = dict(poster, id=2, eventtype='Oral', paper_url='', related_events_ids=[1])
    position = dict(poster, id=3, name='Position: Evaluate carefully',
                    sourceurl='https://openreview.net/group?id=ICML.cc/2026/Position_Paper_Track',
                    paper_url='https://openreview.net/forum?id=ICML_POSITION')
    excluded = [dict(poster, id=4, sourceurl='TMLR-2026'),
                dict(poster, id=5, sourceurl='https://openreview.net/group?id=ICML.cc/2026/Workshop'),
                dict(poster, id=6, decision='Reject')]
    data = {'count': 6, 'next': None, 'results': [poster, oral, position, *excluded]}
    as_of = datetime(2026, 9, 27, tzinfo=timezone.utc)
    records = parse_icml(json.dumps(data), 2026, as_of=as_of)
    assert [r.extra['publisher_key'] for r in records] == [poster['paper_url'], position['paper_url']]
    assert all(r.year == 2026 for r in records)
    position['endtime'] = None  # virtual presentation without a scheduled session
    assert len(parse_icml(json.dumps(data), 2026, as_of=as_of)) == 2
    with pytest.raises(ValueError, match='not yet concluded'):
        parse_icml(json.dumps(data), 2026, as_of=datetime(2026, 1, 1, tzinfo=timezone.utc))
    poster['endtime'] = '2025-07-09T02:45:00-07:00'
    with pytest.raises(ValueError, match='event year'):
        parse_icml(json.dumps(data), 2026, as_of=as_of)


@pytest.mark.asyncio
async def test_icml_missing_pmlr_volume_uses_official_catalogue():
    import json
    from types import SimpleNamespace
    import httpx
    from app.collectors.publisher_toc import fetch_official_inventory
    row = {'id': 1, 'name': 'Learning', 'authors': [{'fullname': 'Ada Lovelace'}],
           'eventtype': 'Poster', 'decision': 'Accept (regular)',
           'sourceurl': 'https://openreview.net/group?id=ICML.cc/2023/Conference',
           'paper_url': 'https://openreview.net/forum?id=ICML_2023',
           'endtime': '2023-07-28T12:00:00+00:00'}
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == 'https://proceedings.mlr.press/':
            return httpx.Response(200, text='<html>No volume yet</html>', headers={'Content-Type': 'text/html'})
        assert str(request.url) == 'https://icml.cc/static/virtual/data/icml-2023-orals-posters.json'
        return httpx.Response(200, text=json.dumps({'count': 1, 'results': [row]}), headers={'Content-Type': 'application/json'})
    class Limiter:
        async def acquire(self): pass
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        records = await fetch_official_inventory(client, Limiter(), SimpleNamespace(abbr='ICML'), 2023)
    assert len(calls) == 2 and records[0].title == 'Learning'


def eccv_catalogue_fixture(year=2026):
    poster = {'id': 1, 'sourceid': 123, 'name': 'Reasoning with <SEG> tokens',
              'authors': [{'fullname': 'Ada Lovelace'}], 'eventtype': 'Poster',
              'decision': 'Accept Poster',
              'sourceurl': f'https://openreview.net/group?id=thecvf.com/ECCV/{year}/Conference',
              'virtualsite_url': f'/virtual/{year}/poster/1',
              'paper_pdf_url': f'https://media.eventhosts.cc/Conferences/ECCV{year}/pdfs/123.pdf',
              'endtime': f'{year}-09-12T03:30:00-07:00'}
    oral = dict(poster, id=2, sourceid=-123, eventtype='Oral', decision=None,
                related_events_ids=[1])
    spotlight = dict(oral, id=3, eventtype='Spotlight')
    workshop = dict(poster, id=4, sourceurl='Workshop')
    return {'count': 4, 'next': None, 'results': [poster, oral, spotlight, workshop]}


def test_eccv_published_catalogue_deduplicates_presentations_and_keeps_model_tokens():
    import json
    from datetime import datetime, timezone
    from app.collectors.publisher_toc import parse_eccv_catalogue
    data = eccv_catalogue_fixture()
    records = parse_eccv_catalogue(json.dumps(data), 2026, as_of=datetime(2026, 9, 27, tzinfo=timezone.utc))
    assert len(records) == 1
    assert records[0].title == 'Reasoning with <SEG> tokens'
    assert records[0].extra['publisher_key'] == 'https://eccv.ecva.net/virtual/2026/poster/1'
    assert records[0].year == 2026
    with pytest.raises(ValueError, match='not yet concluded'):
        parse_eccv_catalogue(json.dumps(data), 2026, as_of=datetime(2026, 9, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize('invalid', ['page', 'orphan', 'event', 'decision', 'link', 'date', 'year', 'duplicate_paper'])
def test_eccv_catalogue_fails_closed_on_unverified_metadata(invalid):
    import json
    from datetime import datetime, timezone
    from app.collectors.publisher_toc import parse_eccv_catalogue
    data = eccv_catalogue_fixture()
    row = data['results'][0]
    if invalid == 'page': data['next'] = 'next-page'
    elif invalid == 'orphan': data['results'][1]['related_events_ids'] = []
    elif invalid == 'event': row['eventtype'] = 'Journal'
    elif invalid == 'decision': row['decision'] = None
    elif invalid == 'link': row['paper_pdf_url'] = 'https://example.org/arbitrary.pdf'
    elif invalid == 'date': row['endtime'] = None
    elif invalid == 'year': row['endtime'] = '2025-09-12T03:30:00-07:00'
    else:
        data['results'].append(dict(row, id=5, virtualsite_url='/virtual/2026/poster/5'))
        data['count'] += 1
    with pytest.raises(ValueError):
        parse_eccv_catalogue(json.dumps(data), 2026, as_of=datetime(2026, 9, 27, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_eccv_missing_ecva_volume_uses_catalogue_without_requesting_pdfs():
    from types import SimpleNamespace
    import httpx
    from app.collectors.publisher_toc import fetch_official_inventory
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if str(request.url) == 'https://www.ecva.net/papers.php':
            return httpx.Response(200, text='<html>Earlier proceedings</html>', headers={'Content-Type': 'text/html'})
        assert str(request.url) == 'https://eccv.ecva.net/static/virtual/data/eccv-2024-orals-posters.json'
        return httpx.Response(200, json=eccv_catalogue_fixture(2024))
    class Limiter:
        async def acquire(self): pass
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        records = await fetch_official_inventory(client, Limiter(), SimpleNamespace(abbr='ECCV'), 2024)
    assert len(calls) == 2 and len(records) == 1


@pytest.mark.asyncio
async def test_eccv_partial_ecva_volume_is_not_masked_by_fallback():
    from types import SimpleNamespace
    import httpx
    from app.collectors.publisher_toc import fetch_official_inventory
    def handler(request):
        assert str(request.url) == 'https://www.ecva.net/papers.php'
        return httpx.Response(200, text='papers/eccv_2024/papers_ECCV/html/broken.php', headers={'Content-Type': 'text/html'})
    class Limiter:
        async def acquire(self): pass
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match='incomplete'):
            await fetch_official_inventory(client, Limiter(), SimpleNamespace(abbr='ECCV'), 2024)


def test_eccv_catalogue_audit_replays_saved_metadata(tmp_path):
    import hashlib
    import json
    from scripts.audit_publications import official_records
    url = 'https://eccv.ecva.net/static/virtual/data/eccv-2024-orals-posters.json'
    cache = tmp_path / ('toc-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.txt')
    cache.write_text(json.dumps(eccv_catalogue_fixture(2024)), encoding='utf-8')
    records = official_records({'venue': 'ECCV', 'year': 2024, 'url': url}, tmp_path)
    assert len(records) == 1 and records[0].year == 2024


def test_official_import_matches_author_initials_without_creating_duplicate(db, sample_venue):
    preprint = RawPaper(source='openalex', venue_key='W1234', title='A real publication', year=2023,
                        authors=['Lovelace, Ada', 'Turing, A.'], doi='10.48550/arxiv.2301.12345')
    old, _ = upsert_paper(db, preprint, sample_venue); db.commit()
    key = 'https://papers.nips.cc/paper/official'
    official = RawPaper(source='manual', venue_key=key, title=old.title, year=2024,
                        authors=['Lovelace, Ada', 'Turing, Alan'], official_url=key,
                        extra={'publisher_key': key, 'provenance': 'publisher_toc'})
    result = apply_records(db, [official], sample_venue)
    assert result['counts']['updated'] == 1 and result['counts']['years_corrected'] == 1
    assert db.query(Paper).count() == 1 and old.arxiv_id == '2301.12345'


def test_publisher_detail_requires_matching_title_and_explicit_doi():
    from app.collectors.publisher_toc import _raw, publication_detail_doi
    raw = _raw("https://publisher.example/1", "A Paper", ["Jane Doe"], 2025)
    body = '<meta name="citation_title" content="A Paper"><meta name="citation_doi" content="10.1234/real">'
    assert publication_detail_doi(body, raw) == "10.1234/real"
    with pytest.raises(ValueError):
        publication_detail_doi(body.replace("A Paper", "Different Paper"), raw)
    with pytest.raises(ValueError):
        publication_detail_doi('<a href="https://doi.org/10.1234/guessed">link</a>', raw)
