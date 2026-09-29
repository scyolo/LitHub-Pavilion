"""Publisher metadata safety tests; all inventories are mocked, never live."""
from types import SimpleNamespace

import httpx
import pytest

from app.collectors.crossref import fetch_prefix, identify_venue, item_to_raw, publication_date
from app.models import Paper, Venue
from scripts.repair_publications import apply_items


def article(**changes):
    value = {"DOI": "10.1609/aaai.v38i1.12345", "title": ["Models &amp; Planning"],
             "type": "proceedings-article", "published": {"date-parts": [[2024, 2, 20]]},
             "container-title": ["Proceedings of the AAAI Conference on Artificial Intelligence"],
             "author": [{"given": "Ada", "family": "Lovelace"}]}
    value.update(changes)
    return value


def test_publisher_html_is_not_part_of_title_or_identity():
    raw = item_to_raw(article())
    assert raw.title == "Models & Planning"
    assert raw.publication_date == "2024-02-20"
    assert raw.source == "manual"
    assert raw.extra["provenance"] == "crossref_publisher"


@pytest.mark.parametrize("parts,expected", [([2024], (2024, None)), ([2024, 2, 30], (2024, None)), ([2024, 2, 29], (2024, "2024-02-29"))])
def test_partial_dates_are_not_invented(parts, expected):
    assert publication_date(article(published={"date-parts": [parts]})) == expected


def test_issue_year_wins_over_early_access():
    value = article(**{"published-print": {"date-parts": [[2025]]}, "published-online": {"date-parts": [[2023, 12, 1]]}})
    assert publication_date(value) == (2025, None)


def test_venue_requires_both_namespace_and_container():
    venue = SimpleNamespace(type="conf")
    assert identify_venue(article(), {"AAAI": venue}) is venue
    assert identify_venue(article(DOI="10.9999/not-aaai"), {"AAAI": venue}) is None
    assert identify_venue(article(**{"container-title": ["AAAI Workshop"]}), {"AAAI": venue}) is None
    assert identify_venue(article(DOI="10.18653/v1/2025.findings-acl.1", **{"container-title": ["Findings of the Association for Computational Linguistics"]}), {"ACL": venue}) is None
    assert identify_venue(article(DOI='10.18653/v1/2025.emnlp-industry.1', **{'container-title': ['Proceedings of the Conference on Empirical Methods in Natural Language Processing: Industry Track']}), {'EMNLP': venue}) is None


def test_journal_requires_issn_and_full_title():
    venue = SimpleNamespace(type="journal", name="Pattern Recognition", issn="0031-3203")
    value = article(type="journal-article", ISSN=["0031-3203"], **{"container-title": ["Pattern Recognition"]})
    assert identify_venue(value, {"PR": venue}) is venue
    value["container-title"] = ["Pattern Recognition Letters"]
    assert identify_venue(value, {"PR": venue}) is None


@pytest.mark.asyncio
async def test_same_crossref_cursor_is_valid_for_different_pages():
    pages = iter([
        {"items": [article()], "total-results": 2, "next-cursor": "same"},
        {"items": [article(DOI="10.1609/aaai.v38i1.12346")], "total-results": 2, "next-cursor": "same"},
    ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"message": next(pages)}))) as client:
        assert len(await fetch_prefix(client, "10.1609", 2023, 2026)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("second", [[], [article()]])
async def test_repeated_or_truncated_pages_never_count_as_complete(second):
    pages = iter([
        {"items": [article()], "total-results": 2, "next-cursor": "same"},
        {"items": second, "total-results": 2, "next-cursor": "same"},
    ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"message": next(pages)}))) as client:
        with pytest.raises(ValueError):
            await fetch_prefix(client, "10.1609", 2023, 2026)


def test_publisher_repair_idempotent_and_identity_conflict_safe(db):
    venue = Venue(abbr="AAAI", name="AAAI", type="conf", dblp_stream="conf/aaai", ccf_level="A", active=1)
    db.add(venue); db.commit()
    first = apply_items(db, [article()], range(2023, 2027))
    assert first["counts"]["new"] == 1
    paper = db.query(Paper).one()
    paper.year = 2023
    paper.publication_date = "2023-01-02"
    db.commit()
    second = apply_items(db, [article()], range(2023, 2027))
    assert second["counts"]["years_corrected"] == 1
    assert paper.year == 2024 and paper.publication_date == "2024-02-20"
    assert db.query(Paper).count() == 1 and paper.venue_confirmed == 1
    conflict = article(title=["Completely Unrelated Publication"], author=[{"family": "Other"}])
    third = apply_items(db, [conflict], range(2023, 2027))
    assert third["counts"]["identity_conflicts"] == 1
    assert paper.title == "Models & Planning"


def test_ecai_book_chapter_requires_official_series_and_conference():
    from types import SimpleNamespace
    from app.collectors.crossref import identify_venue, item_to_raw
    venue = SimpleNamespace(abbr='ECAI', type='conf')
    item = {'DOI': '10.3233/FAIA250787', 'type': 'book-chapter', 'container-title': ['Frontiers in Artificial Intelligence and Applications', 'ECAI 2025'], 'title': ['Reasoning'], 'published': {'date-parts': [[2025]]}}
    assert identify_venue(item, {'ECAI': venue}) is venue
    assert item_to_raw(item).year == 2025
    item['container-title'][-1] = 'ECAI 2025 Workshop'
    assert identify_venue(item, {'ECAI': venue}) is None


def test_taslp_continuation_issn_requires_verified_name_and_config():
    from types import SimpleNamespace
    from app.collectors.crossref import identify_venue, journal_identities
    venue = SimpleNamespace(abbr='TASLP', issn='2329-9290', name='IEEE/ACM Transactions on Audio, Speech, and Language Processing', type='journal')
    item = {'DOI': '10.1109/taslpro.2025.1', 'type': 'journal-article', 'container-title': ['IEEE Transactions on Audio Speech and Language Processing'], 'ISSN': ['2998-4173']}
    assert identify_venue(item, {'TASLP': venue}) is venue
    item['container-title'] = ['Unrelated Proceedings']
    assert identify_venue(item, {'TASLP': venue}) is None
    venue.issn = '0000-0000'
    assert len(journal_identities(venue)) == 1


@pytest.mark.asyncio
async def test_icra_inventory_uses_exact_container_filter():
    from app.collectors.crossref import fetch_container
    title = '2023 IEEE International Conference on Robotics and Automation (ICRA)'
    item = article(DOI='10.1109/icra48891.2023.10161017', **{'container-title': [title]})
    def serve(request):
        assert 'container-title:' + title in request.url.params['filter']
        return httpx.Response(200, json={'message': {'items': [item], 'total-results': 1}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        assert len(await fetch_container(client, title, 2023, 2026)) == 1
    venue = SimpleNamespace(type='conf')
    assert identify_venue(item, {'ICRA': venue}) is venue
    item['container-title'] = [title + ' Workshops']
    assert identify_venue(item, {'ICRA': venue}) is None


def ecml_chapter(conference_year=2025, imprint_year=2026):
    title = 'Machine Learning and Knowledge Discovery in Databases. Research Track'
    return article(DOI='10.1007/978-3-032-06078-5_1', type='book-chapter', **{
        'container-title': ['Lecture Notes in Computer Science', title],
        'published-print': {'date-parts': [[imprint_year, 1, 2]]},
        '_ecml_parent': {'DOI': '10.1007/978-3-032-06078-5', 'type': 'book', 'title': [title],
            'subtitle': [f'European Conference, ECML PKDD {conference_year}, Porto, Proceedings, Part IV']},
    })


def test_ecml_year_comes_from_verified_parent_not_imprint():
    from app.collectors.crossref import ecml_conference_year
    venue = SimpleNamespace(type='conf')
    item = ecml_chapter()
    assert identify_venue(item, {'ECML-PKDD': venue}) is venue
    assert ecml_conference_year(item) == 2025
    assert item_to_raw(item).year == 2025
    assert item_to_raw(item).publication_date is None
    assert item_to_raw(ecml_chapter(2022, 2023)).year == 2022


@pytest.mark.parametrize('invalid', ['wrong_parent', 'workshop', 'no_parent', 'wrong_container'])
def test_ecml_does_not_infer_acceptance_from_title_alone(invalid):
    item = ecml_chapter()
    if invalid == 'wrong_parent': item['_ecml_parent']['DOI'] = '10.1007/978-0-000-00000-0'
    elif invalid == 'workshop': item['_ecml_parent']['subtitle'] = ['European Conference, ECML PKDD 2025, Workshops, Proceedings']
    elif invalid == 'no_parent': del item['_ecml_parent']
    else: item['container-title'] = ['Unrelated book']
    assert identify_venue(item, {'ECML-PKDD': SimpleNamespace(type='conf')}) is None


@pytest.mark.asyncio
async def test_ecml_inventory_checks_parent_and_excludes_old_conference(monkeypatch):
    from app.collectors import crossref
    from unittest.mock import AsyncMock
    valid, old = ecml_chapter(), ecml_chapter(2022, 2023)
    old['DOI'] = '10.1007/978-3-031-26390-3_1'
    old['_ecml_parent']['DOI'] = '10.1007/978-3-031-26390-3'
    parents = {v['_ecml_parent']['DOI']: v['_ecml_parent'] for v in (valid, old)}
    chapter_items = [{k: v for k, v in item.items() if k != '_ecml_parent'} for item in (valid, old)]
    monkeypatch.setattr(crossref, 'ECML_CONTAINERS', (valid['container-title'][-1],))
    inventory = AsyncMock(return_value=chapter_items)
    monkeypatch.setattr(crossref, 'fetch_container', inventory)
    monkeypatch.setattr(crossref.AsyncTokenBucket, 'acquire', AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={'message': parents[req.url.path.split('/works/')[1]]}))) as client:
        result = await crossref.fetch_ecml(client, 'ECML-PKDD', 2023, 2026)
    assert len(result) == 1 and result[0]['DOI'] == valid['DOI']
    assert inventory.call_args.args[3] == 2027  # delayed imprint included in discovery


@pytest.mark.asyncio
async def test_container_with_comma_uses_verified_isbn_not_broken_filter():
    from app.collectors.crossref import ECML_CONTAINERS, fetch_container
    def serve(request):
        assert 'isbn:9783032376855' in request.url.params['filter']
        assert 'container-title:' not in request.url.params['filter']
        return httpx.Response(200, json={'message': {'items': [], 'total-results': 0}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        assert await fetch_container(client, ECML_CONTAINERS[-1], 2023, 2027) == []


@pytest.mark.asyncio
async def test_scheduled_crossref_fallback_repairs_year_but_stays_partial(db, session_factory, monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.pipeline import CrawlPipeline
    venue = Venue(abbr='AAAI', name='AAAI', type='conf', dblp_stream='conf/aaai',
                  openalex_source_id='S123', ccf_level='A', active=1)
    db.add(venue); db.commit()
    apply_items(db, [article()], [2024])
    paper = db.query(Paper).one(); paper.year = 2023; paper.publication_date = '2023-01-01'; db.commit()
    raw = item_to_raw(article()); raw.extra['crossref_item'] = article()
    monkeypatch.setattr('app.services.pipeline.fetch_official_inventory', AsyncMock(return_value=[]))
    monkeypatch.setattr('app.services.pipeline.fetch_configured_inventory', AsyncMock(return_value=[raw]))
    monkeypatch.setattr('app.services.pipeline.fetch_works_by_source', AsyncMock(return_value=[]))
    pipeline = CrawlPipeline(session_factory)
    records, partial = await pipeline._collect_unit_async(db, venue, 2024, False)
    assert partial and records == [raw]
    _, new, updated = pipeline._ingest_batch_sync(db, records, venue, 2024)
    assert (new, updated) == (0, 1)
    assert paper.year == 2024 and paper.publication_date == '2024-02-20'


@pytest.mark.asyncio
async def test_configured_inventory_filters_year_and_reuses_run_cache(monkeypatch):
    from app.collectors import crossref
    from unittest.mock import AsyncMock
    fetch = AsyncMock(return_value=[article(), article(DOI='10.1609/aaai.v39i1.999', published={'date-parts': [[2025]]})])
    monkeypatch.setattr(crossref, 'fetch_prefix', fetch)
    venue = SimpleNamespace(abbr='AAAI', type='conf')
    cache = {}
    for _ in range(2):
        records = await crossref.fetch_configured_inventory(None, venue, 2024, cache=cache)
        assert len(records) == 1 and records[0].extra['crossref_item']['DOI'] == article()['DOI']
    assert fetch.await_count == 1


def test_crossref_title_removes_mathml_and_small_caps_without_losing_text():
    from app.collectors.crossref import metadata_text
    value = '<scp>DiBiMT</scp>: <mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML"><mml:msub><mml:mi>λ</mml:mi><mml:mn>2</mml:mn></mml:msub></mml:math> &amp; fairness'
    assert metadata_text(value) == 'DiBiMT: λ2 & fairness'
    assert metadata_text('A &lt; B &amp; C') == 'A < B & C'
    assert metadata_text('Use &lt;SEG&gt;, <safe> and <SYNTACT> tokens') == 'Use <SEG>, <safe> and <SYNTACT> tokens'
    assert metadata_text('&lt;jats:italic&gt;Learning&lt;/jats:italic&gt;') == 'Learning'


def test_crossref_typographic_title_repair_does_not_require_changed_authors(db):
    from app.models import Venue
    venue = Venue(abbr='AAAI', name='AAAI', dblp_stream='conf/aaai', type='conf', ccf_level='A', active=1)
    db.add(venue); db.commit()
    item = article(title=['MI3C: Learn Better'])
    apply_items(db, [item], [2024])
    paper = db.query(Paper).one()
    paper.title = 'MI 3 C: Learn Better'
    paper.title_norm = 'mi 3 c learn better'
    paper.year = 2023
    db.commit()
    item['author'] = [{'family': 'Smith', 'given': 'A.'}]  # abbreviated metadata is not a basis for semantic title edits
    result = apply_items(db, [item], [2024])
    assert not result['conflicts']
    assert paper.year == 2024 and paper.title == 'MI3C: Learn Better'
    item['title'] = ['A Different Scientific Result']
    result = apply_items(db, [item], [2024])
    assert result['counts']['identity_conflicts'] == 1
    assert paper.title == 'MI3C: Learn Better'


def test_teletype_markup_is_not_part_of_the_published_title():
    from app.collectors.crossref import metadata_text
    assert metadata_text("<tt>PASTA</tt>: Modeling Participant States") == "PASTA: Modeling Participant States"
    assert metadata_text("&lt;tt&gt;L2CEval&lt;/tt&gt; : Evaluation") == "L2CEval : Evaluation"
    assert metadata_text("<SEG> and <safe> tokens") == "<SEG> and <safe> tokens"


def test_title_does_not_include_inline_graphic_accessibility_description():
    from app.collectors.crossref import metadata_text
    title = '<jats:inline-graphic><jats:alt-text>A sketch of a pencil writing</jats:alt-text></jats:inline-graphic> NoTeS-Bank: Benchmarking Vision-Language Models'
    assert metadata_text(title) == 'NoTeS-Bank: Benchmarking Vision-Language Models'


def test_acl_short_is_not_a_ccf_main_track():
    assert identify_venue(article(DOI="10.18653/v1/2024.acl-short.1", **{"container-title": ["Proceedings of the Annual Meeting of the Association for Computational Linguistics"]}), {"ACL": object()}) is None


def test_crossref_cannot_regress_final_publisher_issue_metadata(db, sample_venue):
    sample_venue.abbr = "AAAI"
    sample_venue.type = "conf"
    db.commit()
    value = article()
    first = apply_items(db, [value], range(2023,2027))
    assert first["counts"]["new"] == 1
    paper = db.query(Paper).one()
    paper.publisher_key = "https://ojs.aaai.org/index.php/AAAI/article/view/12345"
    paper.title = "Models & Planning: A Publisher Revision"
    from app.cleaning import normalize_title
    paper.title_norm = normalize_title(paper.title)
    paper.year = 2025
    paper.publication_date = "2025-02-01"
    db.commit()
    # Same final title here isolates early-access year precedence.
    value["title"] = [paper.title]
    result = apply_items(db, [value], range(2023,2027))
    assert result["counts"]["official_metadata_preserved"] == 1
    assert paper.year == 2025
    assert paper.publication_date == "2025-02-01"


@pytest.mark.asyncio
async def test_journal_inventory_unions_print_dates_without_duplicate_callbacks(monkeypatch):
    from app.collectors.crossref import fetch_journal
    from unittest.mock import AsyncMock
    import app.collectors.crossref as crossref
    monkeypatch.setattr(crossref.AsyncTokenBucket, "acquire", AsyncMock())
    visited, received = [], []
    def serve(request):
        field = request.url.params["filter"]
        visited.append(field)
        records = [article()]
        if "from-print-pub-date:" in field:
            records.append(article(DOI="10.1609/aaai.v38i1.54321"))
        return httpx.Response(200, json={"message": {"items": records, "total-results": len(records)}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
        records = await fetch_journal(client, "0162-8828", 2023, 2026,
                                      on_page=lambda _,p,n,t,b: received.extend(b))
    assert len(visited) == 2
    assert len(records) == len(received) == 2
    assert len({x["DOI"] for x in records}) == 2
