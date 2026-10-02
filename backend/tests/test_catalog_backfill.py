import csv

import pytest

from app.collectors.crossref import request_with_retry
from scripts.backfill_catalog_journals import allowed_journals


def test_backfill_rejects_c_rank_nonjournal_and_missing_identity(tmp_path):
    path = tmp_path / "venues.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["abbr", "type", "ccf_level", "issn"])
        writer.writeheader()
        writer.writerows([
            {"abbr": "TOCHI", "type": "journal", "ccf_level": "A", "issn": "1073-0516"},
            {"abbr": "BJournal", "type": "journal", "ccf_level": "B", "issn": "0000-0001"},
            {"abbr": "CJournal", "type": "journal", "ccf_level": "C", "issn": "0000-0002"},
            {"abbr": "Conference", "type": "conf", "ccf_level": "A", "issn": "0000-0003"},
            {"abbr": "Unmapped", "type": "journal", "ccf_level": "A", "issn": ""},
        ])
    assert set(allowed_journals(path)) == {"TOCHI", "BJournal"}


@pytest.mark.asyncio
async def test_crossref_retry_honors_retry_after():
    import httpx

    from app.collectors import crossref

    calls = []

    async def fake_sleep(seconds):
        calls.append(seconds)

    responses = iter([
        httpx.Response(429, headers={"retry-after": "2"}),
        httpx.Response(200, json={"message": {"items": []}}),
    ])

    class Client:
        async def get(self, url, params=None):
            return next(responses)

    original = crossref.asyncio.sleep
    crossref.asyncio.sleep = fake_sleep
    try:
        response = await request_with_retry(Client(), "https://api.crossref.org/works")
    finally:
        crossref.asyncio.sleep = original
    assert response.status_code == 200
    assert calls == [2.0]


@pytest.mark.asyncio
async def test_pages_are_retained_on_later_network_failure_and_tagged(db, session_factory, tmp_path, monkeypatch):
    from argparse import Namespace
    from contextlib import asynccontextmanager
    from pathlib import Path

    import httpx

    from app.models import Direction, DirectionRule, Paper, PaperDirection, Venue
    from scripts import backfill_catalog_journals as module
    venue=Venue(abbr='TODS',name='ACM Transactions on Database Systems',dblp_stream='journals/tods',issn='0362-5915',type='journal',ccf_level='A')
    direction=Direction(code='graph',name='Graph',enabled=1,min_score=2)
    db.add_all([venue,direction]);db.flush()
    db.add(DirectionRule(direction_id=direction.id,keyword='graph',weight=1,field='title',enabled=1));db.commit()
    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'message':{'ISSN':['0362-5915'],'title':venue.name}}))) as c:
            yield c
    async def fetch(c,issn,y1,y2,**kwargs):
        kwargs['on_page']('0362-5915:pub-date',1,1,2,[{'DOI':'10.1145/123.999','title':['Graph query processing'],'type':'journal-article','container-title':[venue.name],'ISSN':[issn],'published':{'date-parts':[[2024]]},'author':[{'given':'Ada','family':'Smith'}]}])
        raise httpx.ReadTimeout('later page timed out')
    monkeypatch.setattr(module,'make_client',client);monkeypatch.setattr(module,'fetch_journal',fetch)
    args=Namespace(database=Path(session_factory.kw['bind'].url.database),venue=['TODS'],year_from=2023,year_to=2026,output=tmp_path/'result',apply=True)
    report=await module.run(args)
    assert report['units'][0]['status']=='partial'
    assert report['units'][0]['complete'] is False
    paper=db.query(Paper).filter_by(doi='10.1145/123.999').one()
    assert db.query(PaperDirection).filter_by(paper_id=paper.id,direction_id=direction.id).count()==1
    assert not list(args.output.glob('*crossref.json'))


@pytest.mark.parametrize('abbr,name,publisher,issn', [
    ('JSA', 'Journal of Systems Architecture: Embedded Software Design', 'Journal of Systems Architecture', '1383-7621'),
    ('Performance Evaluation: An International Journal', 'Performance Evaluation: An International Journal', 'Performance Evaluation', '0166-5316'),
    ('SoSyM', 'Software and Systems Modeling', 'Software & Systems Modeling', '1619-1366'),
    ('IPM', 'Information Processing and Management', 'Information Processing & Management', '0306-4573'),
    ('CSCW Journal', 'Computer Supported Cooperative Work', 'Computer Supported Cooperative Work (CSCW)', '0925-9724'),
])
def test_verified_journal_name_variants_require_exact_catalog_identity(abbr, name, publisher, issn):
    from types import SimpleNamespace

    from app.collectors.crossref import identify_venue
    v = SimpleNamespace(abbr=abbr, name=name, issn=issn, type='journal')
    row = {'DOI': '10.1000/test', 'type': 'journal-article', 'container-title': [publisher], 'ISSN': [issn]}
    assert identify_venue(row, {abbr: v}) is v
    v.issn = '0000-0000'
    assert identify_venue(row, {abbr: v}) is None
    v.issn = issn
    v.name = 'Unrelated source'
    assert identify_venue(row, {abbr: v}) is None


@pytest.mark.asyncio
async def test_crossref_transport_failures_are_retried_but_bounded(monkeypatch):
    import httpx

    from app.collectors import crossref
    delays = []
    async def sleep(seconds):
        delays.append(seconds)
    monkeypatch.setattr(crossref.asyncio, 'sleep', sleep)
    class Client:
        def __init__(self): self.calls = 0
        async def get(self, url, params=None):
            self.calls += 1
            raise httpx.ConnectError('temporary network failure')
    client = Client()
    with pytest.raises(httpx.ConnectError):
        await request_with_retry(client, 'https://api.crossref.org/works', attempts=3)
    assert client.calls == 3
    assert len(delays) == 2


@pytest.mark.asyncio
async def test_inventory_uses_shared_retry_after_policy(monkeypatch):
    import httpx

    from app.collectors import crossref
    delays = []
    async def sleep(seconds): delays.append(seconds)
    monkeypatch.setattr(crossref.asyncio, 'sleep', sleep)
    responses = iter([
        httpx.Response(429, headers={'retry-after': '2'}),
        httpx.Response(200, json={'message': {'items': [], 'total-results': 0}}),
    ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: next(responses))) as client:
        await crossref._fetch_inventory(client, crossref.API + '/works', 'test', 2023, 2026)
    assert delays == [2.0]


@pytest.mark.asyncio
async def test_bounded_container_query_does_not_change_exact_record_validation():
    import httpx
    from app.collectors.crossref import _fetch_inventory, API
    def serve(req):
        assert req.url.params['query.container-title'] == 'Conference, Volume 1'
        assert req.url.params['cursor'] == '*'
        assert req.url.params['sort'] == 'score'
        return httpx.Response(200,json={'message':{'items':[],'total-results':0}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        assert await _fetch_inventory(client,API+'/works','sample',2023,2026,query={'query.container-title':'Conference, Volume 1'}) == []
