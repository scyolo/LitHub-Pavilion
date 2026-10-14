"""Open full-text evidence must not be confused with a publisher/search page."""
from types import SimpleNamespace

import pytest

from app.services.open_access import best_openalex_url, publisher_open_url


@pytest.mark.parametrize('url', [
    'https://proceedings.mlr.press/v267/fu25f.html',
    'https://openreview.net/forum?id=WCVMqRHWW5',
    'https://papers.nips.cc/paper_files/paper/2025/hash/abc123-Abstract-Conference.html',
    'https://aclanthology.org/2025.emnlp-main.1199/',
    'https://openaccess.thecvf.com/content/ICCV2025/html/Li_Diversity_ICCV_2025_paper.html',
    'https://ojs.aaai.org/index.php/AAAI/article/view/38707',
    'https://www.ijcai.org/proceedings/2025/694',
    'https://proceedings.kr.org/2026/73/',
    'https://jmlr.org/papers/v24/18-080.html',
    'https://www.jair.org/index.php/jair/article/view/14820',
    'https://www.ifaamas.org/Proceedings/aamas2023/pdfs/p5.pdf',
    'https://www.usenix.org/conference/fast23/presentation/kadekodi',
    'https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.SoCG.2023.57',
    'https://www.isca-archive.org/interspeech_2023/wang23m_interspeech.html',
    'https://escholarship.org/uc/item/7z0791h1',
    'https://www.ecva.net/papers/eccv_2024/papers_ECCV/html/123_ECCV_2024_paper.php',
    'https://www.cidrdb.org/cidr2023/papers/p14-hirn.pdf',
    'https://vldb.org/cidrdb/papers/2025/p1-lambrecht.pdf',
    'https://msstconference.org/MSST-history/2024/Papers/msst24-1.1.pdf',
])
def test_recognizes_only_existing_article_level_open_publisher_urls(url):
    result = publisher_open_url(publisher_key=url)
    assert result is not None
    assert result.url == url
    assert result.source


@pytest.mark.parametrize('url', [
    'https://openreview.net/group?id=ICLR.cc/2025/Conference',
    'https://openreview.net/forum?id=',
    'https://aclanthology.org/events/acl-2025/',
    'https://proceedings.mlr.press/v267/',
    'https://papers.nips.cc/',
    'https://www.usenix.org/conference/fast23',
    'https://eccv.ecva.net/virtual/2026/poster/4784',
    'https://ieeexplore.ieee.org/document/12345',
    'https://link.springer.com/article/10.1007/example',
    'https://www.sciencedirect.com/science/article/pii/12345',
    'https://dblp.org/rec/conf/test/paper',
    'https://evil.proceedings.mlr.press/v267/fu25f.html',
    'https://proceedings.mlr.press.evil.example/v267/fu25f.html',
    'https://user:password@proceedings.mlr.press/v267/fu25f.html',
    'javascript:alert(1)', 'http://127.0.0.1/paper.pdf',
])
def test_does_not_promote_search_program_or_closed_publisher_pages(url):
    assert publisher_open_url(publisher_key=url, official_url=url) is None


@pytest.mark.parametrize('doi,expected', [
    ('10.18653/v1/2025.acl-long.10', 'https://aclanthology.org/2025.acl-long.10/'),
    ('10.1609/aaai.v40i20.38707', 'https://ojs.aaai.org/index.php/AAAI/article/view/38707'),
    ('10.24963/ijcai.2025/694', 'https://www.ijcai.org/proceedings/2025/694'),
    ('10.24963/kr.2025/73', 'https://proceedings.kr.org/2025/73/'),
    ('10.1371/journal.pcbi.1010001', 'https://doi.org/10.1371/journal.pcbi.1010001'),
    ('10.4230/lipics.socg.2023.57', 'https://doi.org/10.4230/lipics.socg.2023.57'),
    ('10.14778/3574245.3574246', 'https://doi.org/10.14778/3574245.3574246'),
])
def test_routes_identifiers_only_for_known_open_publications(doi, expected):
    assert publisher_open_url(doi=doi).url == expected


@pytest.mark.parametrize('doi', ['10.1109/tpami.2025.1', '10.1007/s11263-025-1', '10.1016/j.patcog.2025.1', '10.1609/unrelated.1'])
def test_doi_alone_does_not_prove_open_access_for_hybrid_publishers(doi):
    assert publisher_open_url(doi=doi) is None


def test_openalex_checks_all_explicit_open_locations_and_skips_unsafe_links():
    assert best_openalex_url({
        'best_oa_location': {'pdf_url': 'javascript:bad'},
        'locations': [None, {'is_oa': False, 'pdf_url': 'https://closed.example/p.pdf'},
                      {'is_oa': True, 'pdf_url': 'https://repository.example/p.pdf'}],
    }) == 'https://repository.example/p.pdf'
    assert best_openalex_url({'primary_location': {'is_oa': True, 'landing_page_url': 'https://open.example/p'}}) == 'https://open.example/p'
    assert best_openalex_url({'best_oa_location': {'is_oa': False, 'pdf_url': 'https://closed.example/p.pdf'},
                             'open_access': {'is_oa': False, 'oa_url': 'https://closed.example/p'}}) is None
    assert best_openalex_url({'locations': 'malformed', 'open_access': []}) is None


def test_local_backfill_preserves_existing_links_and_archive_metadata(db, session_factory, sample_paper):
    from app.services.links_backfill import backfill_local_links
    sample_paper.official_url = 'https://doi.org/10.5555/test.001'
    sample_paper.publisher_key = 'https://proceedings.mlr.press/v267/fu25f.html'
    sample_paper.pdf_path = '/legacy/archive.pdf'
    db.commit()
    first = backfill_local_links(session_factory)
    db.refresh(sample_paper)
    assert first['publisher_filled'] == 1
    assert sample_paper.oa_url == sample_paper.publisher_key
    assert sample_paper.pdf_path == '/legacy/archive.pdf'
    assert sample_paper.official_url == 'https://doi.org/10.5555/test.001'
    assert backfill_local_links(session_factory)['publisher_filled'] == 0


@pytest.mark.asyncio
async def test_openalex_requests_locations_and_rejects_conflicting_doi(db, session_factory, sample_paper, monkeypatch):
    import httpx
    from app.services import links_backfill
    sample_paper.openalex_id = 'W123'
    db.commit()
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'results': [{
            'id': 'https://openalex.org/W123', 'doi': 'https://doi.org/10.5555/unrelated',
            'locations': [{'is_oa': True, 'pdf_url': 'https://repository.example/wrong.pdf'}],
        }]})
    monkeypatch.setattr(links_backfill, 'settings', SimpleNamespace(openalex_rps=100, links_max_batches=1, contact_email=''))
    monkeypatch.setattr(links_backfill, 'make_client', lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    await links_backfill.run_links_backfill(session_factory)
    db.refresh(sample_paper)
    assert 'locations' in requests[0].url.params['select'].split(',')
    assert sample_paper.oa_url is None
