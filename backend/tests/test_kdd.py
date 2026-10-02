from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.collectors.kdd import CATALOGUES, parse_kdd_research
from app.collectors.publisher_toc import fetch_official_inventory


BODY = '''<h1>KDD 2025 Research Track Papers</h1><table>
<tr><td><strong>Learning &amp; Retrieval</strong><br/>DOI: https://doi.org/10.1145/3711896.3736818</td></tr>
<tr><td>Ada Lovelace (Institute (AI; NLP)); Alan Turing (Lab)</td></tr></table>'''


def test_kdd_research_has_explicit_doi_authors_and_limited_scope():
    paper, = parse_kdd_research(BODY, 2025)
    assert paper.title == 'Learning & Retrieval'
    assert paper.authors == ['Lovelace, Ada', 'Turing, Alan']
    assert paper.doi == '10.1145/3711896.3736818'
    assert paper.official_url == 'https://doi.org/' + paper.doi
    assert paper.extra['inventory_scope'] == 'research_track'
    assert 'oa_pdf' not in paper.extra  # No fabricated OA URL.


@pytest.mark.parametrize('body,year', [
    (BODY, 2024), (BODY.replace('Research Track Papers', 'Workshop Papers'), 2025),
    (BODY.replace('3711896.', '9999999.'), 2025),
    (BODY.replace('DOI:', 'Reference:'), 2025),
    (BODY.replace('Alan Turing (Lab)', 'Alan Turing (Lab'), 2025),
    (BODY.replace('</table>', ''), 2025),
    (BODY + BODY, 2025),
])
def test_kdd_fails_closed_on_wrong_track_edition_doi_or_incomplete_pairs(body, year):
    with pytest.raises(ValueError):
        parse_kdd_research(body, year)


@pytest.mark.asyncio
async def test_kdd_only_reads_official_metadata_not_pdfs():
    requested = []
    def handler(request):
        requested.append(str(request.url))
        assert str(request.url) == CATALOGUES[2025]
        return httpx.Response(200, text=BODY, headers={'content-type': 'text/html'})
    limiter = SimpleNamespace(acquire=AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        papers = await fetch_official_inventory(client, limiter, SimpleNamespace(abbr='SIGKDD'), 2025)
    assert len(papers) == 1 and requested == [CATALOGUES[2025]]


@pytest.mark.asyncio
async def test_scoped_official_inventory_cannot_complete_the_whole_venue(db, session_factory, sample_venue, monkeypatch):
    from app.services.pipeline import CrawlPipeline
    monkeypatch.setattr('app.services.pipeline.fetch_official_inventory', AsyncMock(return_value=parse_kdd_research(BODY, 2025)))
    pipeline = CrawlPipeline(session_factory)
    records, partial = await pipeline._collect_unit_async(db, sample_venue, 2025, False)
    assert len(records) == 1 and partial
    assert 'research_track' in pipeline._collection_issue
