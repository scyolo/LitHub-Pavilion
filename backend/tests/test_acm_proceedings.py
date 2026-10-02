import asyncio

import httpx
import pytest

from app.collectors.acm_proceedings import validate_article, validate_parent, fetch_inventory

TITLE = 'Proceedings of the ACM Web Conference 2024'
PARENT = {'DOI': '10.1145/3589334', 'type': 'proceedings', 'title': [TITLE], 'published': {'date-parts': [[2024, 5, 13]]}}
ARTICLE = {'DOI': '10.1145/3589334.3645350', 'type': 'proceedings-article', 'container-title': [TITLE], 'title': ['A Verified Research Title'], 'author': [{'given': 'Ada', 'family': 'Lovelace'}], 'published': {'date-parts': [[2024, 5, 13]]}}


def test_identity_requires_parent_title_year_and_doi():
    assert validate_parent(PARENT, TITLE, 2024) == '10.1145/3589334'
    assert validate_article(ARTICLE, PARENT, TITLE, 2024)
    for changes in ({'DOI': '10.1145/9999999.12345'}, {'container-title': [TITLE + ' Companion']}, {'type': 'book-chapter'}, {'author': []}, {'published': {'date-parts': [[2023]]}}):
        with pytest.raises(ValueError):
            validate_article({**ARTICLE, **changes}, PARENT, TITLE, 2024)
    with pytest.raises(ValueError):
        validate_parent({**PARENT, 'title': [TITLE + ' Companion']}, TITLE, 2024)


def test_inventory_paginates_checks_identity_and_does_not_claim_track_coverage():
    calls = []
    def respond(request):
        calls.append(request)
        if '/works/10.1145/' in request.url.path:
            return httpx.Response(200, json={'message': PARENT})
        page = 1 if request.url.params['cursor'] == '*' else 2
        item = ARTICLE if page == 1 else {**ARTICLE, 'DOI': '10.1145/3589334.3645351'}
        return httpx.Response(200, json={'message': {'total-results': 2, 'items': [item], 'next-cursor': 'next'}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await fetch_inventory(client, TITLE, 2024, '10.1145/3589334', delay=0)
    result = asyncio.run(run())
    assert len(result['items']) == 2 and result['doi_inventory_complete']
    assert result['full_track_coverage_verified'] is False
    assert result['track_status'] == 'unverified'
    assert all(r.url.host == 'api.crossref.org' for r in calls)


@pytest.mark.parametrize('kind', ['duplicate', 'premature_end', 'wrong_parent'])
def test_bad_inventory_is_not_marked_complete(kind):
    def respond(request):
        if '/works/10.1145/' in request.url.path:
            return httpx.Response(200, json={'message': PARENT})
        items = [ARTICLE, ARTICLE] if kind == 'duplicate' else [] if kind == 'premature_end' else [{**ARTICLE, 'DOI': '10.1145/9999999.1'}]
        return httpx.Response(200, json={'message': {'total-results': 2, 'items': items, 'next-cursor': 'next'}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await fetch_inventory(client, TITLE, 2024, '10.1145/3589334', delay=0)
    with pytest.raises(ValueError):
        asyncio.run(run())


def test_official_full_track_join_requires_exact_title_and_all_authors():
    from app.collectors.acm_proceedings import match_official_track
    inventory = {'parent': PARENT, 'container': TITLE, 'year': 2024, 'items': [ARTICLE]}
    official = [{'title': ARTICLE['title'][0], 'authors': ['Ada Lovelace']}]
    records, issues = match_official_track(inventory, official)
    assert len(records) == 1 and issues == []
    assert records[0].extra['publisher_key'] == 'https://doi.org/' + ARTICLE['DOI']
    assert records[0].extra['verified_track'] == 'official_research_list'
    assert not match_official_track(inventory, [{'title': ARTICLE['title'][0], 'authors': ['Someone Else']}])[0]
    assert not match_official_track(inventory, [{'title': 'Similar but different title', 'authors': ['Ada Lovelace']}])[0]
    with pytest.raises(ValueError, match='Duplicate'):
        match_official_track(inventory, official * 2)


def test_sigir_track_parser_excludes_short_and_demo_and_rejects_truncation(tmp_path):
    import json
    from scripts.import_acm_research_tracks import official_sigir
    rows = [{'submssion_id': f'fp{i:04}', 'title': f'Paper {i}', 'authors': [{'name': 'Ada Lovelace'}]} for i in range(160)]
    rows += [{'submssion_id': 'sp0001', 'title': 'Short', 'authors': [{'name': 'Ada Lovelace'}]}]
    path = tmp_path / 'sigir2024-papers.jsonl'
    path.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf8')
    assert len(official_sigir(tmp_path)) == 160
    path.write_text(json.dumps(rows[0]), encoding='utf8')
    with pytest.raises(ValueError, match='truncated'):
        official_sigir(tmp_path)


def test_wsdm_page_parser_checks_edition_and_author_affiliations(tmp_path):
    from scripts.import_acm_research_tracks import official_wsdm
    header = 'The 17th ACM International WSDM Conference 10.1145/3616855'
    rows = ''.join(f'<strong>Paper {i}</strong><br>Ada Lovelace (Institute (Lab))*; Bob Smith (University)<br>' for i in range(109))
    path = tmp_path / 'wsdm2024-papers.html'
    path.write_text(header + rows + '</div>', encoding='utf8')
    actual = official_wsdm(tmp_path)
    assert len(actual) == 109 and actual[0]['authors'] == ['Ada Lovelace', 'Bob Smith']
    path.write_text(rows + '</div>', encoding='utf8')
    with pytest.raises(ValueError, match='identity'):
        official_wsdm(tmp_path)


def test_acm_mm_2024_parser_reads_only_literal_pairs_and_checks_completeness(tmp_path):
    import json
    from scripts.import_acm_research_tracks import official_mm
    rows = []
    for i in range(1151):
        rows += ['{type:"paperTitle",text:' + json.dumps(str(i + 1) + ' <b>Research ' + str(i) + '<b>') + '}',
                 '{type:"paperAuthor",text:"Ada Lovelace, Bob Smith"}']
    path = tmp_path / 'mm2024-accepted-chunk.txt'
    path.write_text('mainTitle:"Accepted Papers",contents:[' + ','.join(rows) + ']', encoding='utf8')
    result = official_mm(tmp_path)
    assert len(result) == 1151
    assert result[0] == {'title': 'Research 0', 'authors': ['Ada Lovelace', 'Bob Smith']}
    path.write_text('mainTitle:"Accepted Papers",contents:[' + rows[0] + ']', encoding='utf8')
    with pytest.raises(ValueError, match='truncated|count'):
        official_mm(tmp_path)


def test_full_name_reordering_is_allowed_but_name_parts_cannot_be_dropped():
    from app.collectors.acm_proceedings import match_official_track
    item = {**ARTICLE, 'author': [{'given': 'Wenjie', 'family': 'Wang'}]}
    inventory = {'parent': PARENT, 'container': TITLE, 'year': 2024, 'items': [item]}
    records, issues = match_official_track(inventory, [{'title': ARTICLE['title'][0], 'authors': ['Wang Wenjie']}])
    assert len(records) == 1 and not issues
    for name in ['Wang', 'Wei Wang', 'Wenjie Wang Jr']:
        assert not match_official_track(inventory, [{'title': ARTICLE['title'][0], 'authors': [name]}])[0]


def test_www_2024_parser_requires_research_scope_and_complete_cards(tmp_path):
    from scripts.import_acm_research_tracks import official_www
    header = 'Research Tracks The Web Conference 2024 10.1145/3589334'
    card = '<div class="card-title"><strong>Paper {}</strong></div><p class="m-0 p-0">Ada Lovelace, Bob Smith</p>'
    path = tmp_path / 'www2024-research.html'
    path.write_text(header + ''.join(card.format(i) for i in range(405)), encoding='utf8')
    assert len(official_www(tmp_path)) == 405
    path.write_text(header + card.format(1), encoding='utf8')
    with pytest.raises(ValueError, match='count|truncated'):
        official_www(tmp_path)


def test_www_2023_csv_preserves_research_list_and_author_delimiters(tmp_path):
    import csv
    from scripts.import_acm_research_tracks import official_www2023
    path = tmp_path / 'www2023-research.csv'
    with path.open('w', newline='', encoding='utf8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['track', 'track name', 'title', 'authors'])
        for i in range(367):
            writer.writerow(['1', 'Web research', f'Paper {i}', 'Ada Lovelace, Bob Smith and Carol Jones'])
    entries = official_www2023(tmp_path)
    assert len(entries) == 367
    assert entries[0]['authors'] == ['Ada Lovelace', 'Bob Smith', 'Carol Jones']


def test_cikm_full_research_parser_excludes_other_tabs_and_checks_counts(tmp_path):
    from scripts.import_acm_research_tracks import official_cikm2025
    path = tmp_path / 'cikm2025-accepted.html'
    header = '<h1>CIKM 2025</h1><div id="t_01">Full Research Papers</div><div id="ta2_01"><table>'
    rows = ''.join(f'<tr><td>fp{i:04}</td><td>Paper {i}</td><td>Ada Lovelace <i>(Lab, Country)</i> and Bob Smith <i>(Institute, Country)</i></td></tr>' for i in range(442))
    other = '<div id="ta2_02"><table><tr><td>sp1</td><td>Short Paper</td><td>Other Author</td></tr></table></div>'
    path.write_text(header + rows + '</table></div>' + other, encoding='utf8')
    entries = official_cikm2025(tmp_path)
    assert len(entries) == 442
    assert entries[0]['authors'] == ['Ada Lovelace', 'Bob Smith']
    assert not any(e['title'] == 'Short Paper' for e in entries)
    path.write_text(header + '<tr><td>fp1</td><td>Only</td><td>Ada</td></tr></table>', encoding='utf8')
    with pytest.raises(ValueError, match='count|truncated'):
        official_cikm2025(tmp_path)


def test_wsdm2025_parser_checks_count_and_preserves_names(tmp_path):
    from scripts.import_acm_research_tracks import official_wsdm2025
    path = tmp_path / 'wsdm2025-accepted.html'
    header = '<title>Accepted Papers - WSDM 2025</title>'
    rows = ''.join(f'<p><strong>Paper {i}</strong> <em>Ada Lovelace (Lab (Group))*; Bob Smith (School)</em></p>' for i in range(106))
    path.write_text(header + rows, encoding='utf8')
    entries = official_wsdm2025(tmp_path)
    assert len(entries) == 106
    assert entries[0]['authors'] == ['Ada Lovelace', 'Bob Smith']
    path.write_text(header + rows.replace('Paper 0', 'Paper 1', 1)[:-20], encoding='utf8')
    with pytest.raises(ValueError):
        official_wsdm2025(tmp_path)


def test_sigir2025_only_reads_full_papers_section(tmp_path):
    from scripts.import_acm_research_tracks import official_sigir2025
    path = tmp_path / 'sigir2025-accepted.html'
    header = '<title>SIGIR 2025</title><h2 id="full-papers">full papers</h2>'
    row = "<span class='accepted-paper-title'>Paper {}</span><span class='accepted-paper-author'>Ada Lovelace, Bob Smith</span>"
    body = ''.join(row.format(i) for i in range(239))
    path.write_text(header + body + '<h2>short papers</h2>' + row.format('short'), encoding='utf8')
    assert len(official_sigir2025(tmp_path)) == 239
    path.write_text(header + row.format(1) + '<h2>short papers</h2>', encoding='utf8')
    with pytest.raises(ValueError, match='count|truncated'):
        official_sigir2025(tmp_path)


def test_sigir2023_full_paper_parser_checks_count_and_authors(tmp_path):
    from scripts.import_acm_research_tracks import official_sigir2023
    p = tmp_path / 'sigir2023-full.html'
    rows = ''.join(f'<p><strong>● Paper {i}</strong><br />Ada Lovelace, Bob Smith</p>' for i in range(165))
    p.write_text('<title>Full papers - SIGIR 2023</title>' + rows, encoding='utf8')
    result = official_sigir2023(tmp_path)
    assert len(result) == 165 and result[0]['authors'] == ['Ada Lovelace', 'Bob Smith']
    p.write_text('<title>Full papers - SIGIR 2023</title>' + rows[:-20], encoding='utf8')
    with pytest.raises(ValueError, match='count|truncated'):
        official_sigir2023(tmp_path)


def test_wsdm2023_parser_rejects_incomplete_list(tmp_path):
    from scripts.import_acm_research_tracks import official_wsdm2023
    p = tmp_path / 'wsdm2023-accepted.html'
    rows = ''.join(f'<h4>Paper {i}</h4><p>Ada Lovelace (Lab)*; Bob Smith (College)</p>' for i in range(123))
    p.write_text('<title>Accepted Papers | WSDM 2023</title>' + rows, encoding='utf8')
    entries = official_wsdm2023(tmp_path)
    assert len(entries) == 123 and entries[0]['authors'] == ['Ada Lovelace', 'Bob Smith']
    p.write_text('<title>Accepted Papers | WSDM 2023</title>' + rows[:-20], encoding='utf8')
    with pytest.raises(ValueError, match='count|truncated'):
        official_wsdm2023(tmp_path)


def test_sigir2026_extracts_literal_payload_and_rejects_conflicting_copies(tmp_path):
    import json
    from scripts.import_acm_research_tracks import official_sigir2026
    p = tmp_path / 'sigir2026-home.html'
    block = '<h2>Full Papers</h2>' + ''.join(f'<p>[fp] <i>Paper {i}</i><br />Ada Lovelace, Bob Smith</p>' for i in range(233)) + '<h2>Short Papers</h2><p>[sp] Short</p>'
    def script(text):
        return '<script>self.__next_f.push(' + json.dumps([1, text]) + ')</script>'
    p.write_text('<title>SIGIR 2026</title>' + script(block) * 2, encoding='utf8')
    assert len(official_sigir2026(tmp_path)) == 233
    p.write_text('<title>SIGIR 2026</title>' + script(block) + script(block.replace('Paper 1', 'Changed 1')), encoding='utf8')
    with pytest.raises(ValueError):
        official_sigir2026(tmp_path)
    p.write_text('<title>SIGIR 2026</title>' + script(block.replace('<p>[fp] <i>Paper 0</i><br />Ada Lovelace, Bob Smith</p>', '')), encoding='utf8')
    with pytest.raises(ValueError):
        official_sigir2026(tmp_path)


def test_sigir2023_title_outside_bold_cannot_merge_adjacent_papers(tmp_path):
    from scripts.import_acm_research_tracks import official_sigir2023
    p = tmp_path / 'sigir2023-full.html'
    rows = '<p><strong>● Triple Structural Information</strong> Recommendation<br />Jiahao Liu, Dongsheng Li</p>'
    rows += '<p><strong>● Uncertainty Quantification</strong><br />Jyun-Yu Jiang, Wei-Cheng Chang</p>'
    rows += ''.join(f'<p><strong>● Other {i}</strong><br />Ada Lovelace</p>' for i in range(163))
    p.write_text('SIGIR | Taipei | Taiwan | 2023 Full papers' + rows, encoding='utf8')
    result = official_sigir2023(tmp_path)
    assert len(result) == 165
    assert result[0]['title'] == 'Triple Structural Information Recommendation'
    assert result[0]['authors'] == ['Jiahao Liu', 'Dongsheng Li']
    assert result[1]['title'] == 'Uncertainty Quantification'


def test_cikm_nested_affiliations_never_become_authors():
    from scripts.import_acm_research_tracks import cikm_author_names
    cell = 'Yongkyung Oh <i>(University <i>(UCLA)</i>, United States)</i>, Sungil Kim <i>(Institute <i>(UNIST)</i>, South Korea)</i> and Alex Bui <i>(University)</i>'
    assert cikm_author_names(cell) == ['Yongkyung Oh', 'Sungil Kim', 'Alex Bui']
    with pytest.raises(ValueError):
        cikm_author_names('Ada <i>(Missing close)')
    with pytest.raises(ValueError):
        cikm_author_names('Ada </i>')


def test_invalid_author_markup_is_retained_as_unresolved_not_guessed():
    from app.collectors.acm_proceedings import match_official_track
    inventory = {'parent': PARENT, 'container': TITLE, 'year': 2024, 'items': [ARTICLE]}
    records, issues = match_official_track(inventory, [{'title': ARTICLE['title'][0], 'authors': [], 'parse_issue': 'Unbalanced affiliation'}])
    assert not records
    assert issues[0]['reason'] == 'official_author_markup_invalid'


def test_duplicate_author_entries_require_same_orcid_and_identical_metadata():
    from app.collectors.acm_proceedings import canonical_authors
    author = {'given': 'Yajun', 'family': 'Jian', 'ORCID': 'https://orcid.org/0009-0009-3383-7791', 'affiliation': [{'name': 'University'}]}
    authors, removed = canonical_authors([author, dict(author)])
    assert authors == [author] and removed == 1
    for second in [{**author, 'ORCID': 'https://orcid.org/0000-0002-4151-8290'}, {**author, 'affiliation': [{'name': 'Elsewhere'}]}]:
        assert len(canonical_authors([author, second])[0]) == 2
    no_id = {'given': 'Same', 'family': 'Name'}
    assert len(canonical_authors([no_id, dict(no_id)])[0]) == 2


def test_matching_does_not_collapse_same_name_distinct_orcid_authors():
    from app.collectors.acm_proceedings import match_official_track
    a = {'given': 'Ada', 'family': 'Lovelace', 'ORCID': 'https://orcid.org/0000-0001-9492-0796'}
    b = {**a, 'ORCID': 'https://orcid.org/0000-0002-4151-8290'}
    item = {**ARTICLE, 'author': [a, b]}
    inventory = {'parent': PARENT, 'container': TITLE, 'year': 2024, 'items': [item]}
    rows, issues = match_official_track(inventory, [{'title': ARTICLE['title'][0], 'authors': ['Ada Lovelace']}])
    assert not rows and issues[0]['reason'] == 'author_mismatch'
    item['author'] = [a, dict(a)]
    rows, issues = match_official_track(inventory, [{'title': ARTICLE['title'][0], 'authors': ['Ada Lovelace']}])
    assert len(rows) == 1 and not issues
    assert rows[0].extra['duplicate_author_entries_collapsed'] == 1


def test_wsdm2026_full_papers_keep_initials_and_exclude_short_papers(tmp_path):
    from scripts.import_acm_research_tracks import official_wsdm2026
    p = tmp_path / 'wsdm2026-accepted.html'
    rows = '<p>Thomas Bailie, Yun Sing Koh and S. Karthik Mukkavilli. HoGA: Graph Attention</p>'
    rows += ''.join(f'<p>Ada Lovelace and Bob Smith. Title {i}</p>' for i in range(99))
    p.write_text('WSDM 2026<h2>Full Papers</h2>' + rows + '<h2>Short Papers</h2><p>Another Author. Short</p>', encoding='utf8')
    result = official_wsdm2026(tmp_path)
    assert len(result) == 100
    assert result[0]['authors'][-1] == 'S. Karthik Mukkavilli'
    assert result[0]['title'] == 'HoGA: Graph Attention'
    p.write_text('WSDM 2026<h2>Full Papers</h2><p>Broken</p><h2>Short Papers</h2>', encoding='utf8')
    with pytest.raises(ValueError):
        official_wsdm2026(tmp_path)


def test_explicit_same_title_parent_partition_is_verified_not_silently_merged():
    other = {**PARENT, 'DOI': '10.1145/9999999'}
    def respond(request):
        if request.url.path.endswith('/10.1145/3589334'):
            return httpx.Response(200, json={'message': PARENT})
        if request.url.path.endswith('/10.1145/9999999'):
            return httpx.Response(200, json={'message': other})
        return httpx.Response(200, json={'message': {'total-results': 2, 'items': [ARTICLE, {**ARTICLE, 'DOI': '10.1145/9999999.123'}]}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await fetch_inventory(client, TITLE, 2024, PARENT['DOI'], delay=0, other_parent_dois=['10.1145/9999999'])
    result = asyncio.run(run())
    assert [i['DOI'] for i in result['items']] == [ARTICLE['DOI']]
    assert result['other_parent_partitions']['10.1145/9999999']['items'][0]['DOI'] == '10.1145/9999999.123'
    assert result['container_count'] == 2 and result['selected_parent_count'] == 1
    assert result['doi_inventory_complete'] and not result['full_track_coverage_verified']
    other['title'] = ['Unrelated Proceedings']
    with pytest.raises(ValueError):
        asyncio.run(run())


def test_www2026_research_list_preserves_ids_and_rejects_missing_rows(tmp_path):
    from scripts.import_acm_research_tracks import official_www2026
    p = tmp_path / 'www2026-research.html'
    header = 'The Web Conference 2026 Accepted Papers - Research Tracks'
    rows = ''.join(f'<li><span class="paper-id">(rfp{i:04})</span>Title {i} — <span class="paper-authors">Ada Lovelace, Bob Smith and Carol Jones</span></li>' for i in range(676))
    p.write_text(header + rows, encoding='utf8')
    result = official_www2026(tmp_path)
    assert len(result) == 676 and result[0]['authors'] == ['Ada Lovelace', 'Bob Smith', 'Carol Jones']
    p.write_text(header + rows.replace('rfp0001','rfp0000'), encoding='utf8')
    with pytest.raises(ValueError):
        official_www2026(tmp_path)
    p.write_text(header + rows[:-20], encoding='utf8')
    with pytest.raises(ValueError):
        official_www2026(tmp_path)
