"""Official, DOI-optional proceedings inventories. HTML/XML metadata only.

Only fixed publishers and main-volume links are accepted. Every parser validates
its expected record count and fails closed on layout drift; no PDF is fetched.
"""
import html
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, parse_qs

from app.cleaning import clean_author_name, clean_title, normalize_arxiv_id, normalize_doi
from app.collectors.dblp import RawPaper
from app.collectors.crossref import metadata_text


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = _Text()
    parser.feed(value or "")
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def _raw(url, title, authors, year, *, arxiv_id=None, doi=None, abstract=None):
    return RawPaper(source="manual", venue_key=url, official_url=url, title=clean_title(title),
                    authors=[clean_author_name(a.strip()) for a in authors if a.strip()], year=year,
                    arxiv_id=normalize_arxiv_id(arxiv_id), doi=normalize_doi(doi),
                    extra={"provenance": "publisher_toc", "publisher_key": url, "abstract": abstract})


def _validate(records, expected):
    if not expected or len(records) != expected or len({r.venue_key for r in records}) != expected:
        raise ValueError(f"Official inventory incomplete or duplicate: parsed {len(records)}, expected {expected}")
    if any(not r.title or not r.authors for r in records):
        raise ValueError("Official inventory has missing titles/authors")
    return records


def neurips_main_volumes(text, year):
    """Follow main-volume links published in the index (new 2025 layout)."""
    paths = re.findall(r'href="(/paper_files/paper/' + str(year) + r'/vol\d+-main-conference)"', text)
    return list(dict.fromkeys('https://papers.nips.cc' + path for path in paths))


def parse_neurips(text, year):
    base = "https://papers.nips.cc"
    pattern = rf'/paper_files/paper/{year}/hash/[^"\s]+-Abstract(?:-Conference|-Datasets_and_Benchmarks)?\.html'
    expected = len(re.findall(r'href="(' + pattern + ')"', text))
    records = []
    for block in re.findall(r'<li\b[^>]*>(.*?)</li>', text, re.S):
        link = re.search(r'<a\b[^>]*href="(' + pattern + r')"[^>]*>(.*?)</a>', block, re.S)
        authors = re.search(r'<span\b[^>]*class="paper-authors"[^>]*>(.*?)</span>', block, re.S)
        if link and authors:
            records.append(_raw(base + link[1], plain(link[2]), plain(authors[1]).split(','), year))
    return _validate(records, expected)


def pmlr_volumes(text, years):
    result = []
    for block in re.findall(r'<li>(.*?)</li>', text, re.S):
        link = re.search(r'href="(v\d+)"', block)
        scope = re.search(r'Proceedings of (ICML|UAI) (20\d{2})$', plain(block))
        if link and scope and int(scope[2]) in years:
            result.append((scope[1], int(scope[2]), 'https://proceedings.mlr.press/' + link[1] + '/'))
    return result


def parse_pmlr(text, year, url, venue):
    label = "International Conference on Machine Learning" if venue == "ICML" else "Uncertainty in Artificial Intelligence"
    if label.lower() not in plain(text).lower():
        raise ValueError("PMLR volume does not match the requested conference")
    blocks = re.findall(r'<div class="paper">(.*?)</div>', text, re.S)
    records = []
    for block in blocks:
        title = re.search(r'<p class="title">(.*?)</p>', block, re.S)
        authors = re.search(r'<span class="authors">(.*?)</span>', block, re.S)
        link = re.search(r'<a href="([^"]+\.html)">abs</a>', block)
        if title and authors and link:
            landing = urljoin(url, html.unescape(link[1]))
            if not landing.startswith(url):
                raise ValueError("PMLR link points outside the verified volume")
            records.append(_raw(landing, plain(title[1]), plain(authors[1]).split(','), year))
    return _validate(records, len(blocks))


def parse_cvf(text, year, venue):
    prefix = f"/content/{venue}{year}/html/"
    blocks = re.split(r'<dt class="ptitle">', text)[1:]
    records = []
    for block in blocks:
        link = re.search(r'<a href="([^"]+)">(.*?)</a>', block, re.S)
        if not link or not link[1].startswith(prefix):
            raise ValueError("CVF item is outside the requested main proceedings")
        authors = [html.unescape(a) for a in re.findall(r'name="query_author" value="([^"]+)"', block)]
        arxiv = re.search(r'href="(https?://arxiv.org/abs/[^"\s]+)"', block)
        records.append(_raw('https://openaccess.thecvf.com' + link[1], plain(link[2]), authors, year,
                            arxiv_id=arxiv[1] if arxiv else None))
    return _validate(records, len(blocks))


def parse_ijcai(text, year):
    """Parse IJCAI's official proceedings index for one main edition.

    IJCAI exposes one ``paper_wrapper`` per paper and uses the durable
    ``/proceedings/{year}/{number}`` details page as its publication identity.
    PDF links are deliberately ignored.  The parser fails closed when a paper
    block loses its title, author list, or details link.
    """
    opening = re.compile(
        r'<div\b(?=[^>]*\bid=["\']paper\d+["\'])(?=[^>]*\bclass=["\'][^"\']*\bpaper_wrapper\b[^"\']*["\'])[^>]*>',
        re.I,
    )
    starts = list(opening.finditer(text))
    expected = len(re.findall(r'<div\b[^>]*class=["\'][^"\']*\bpaper_wrapper\b', text, re.I))
    if len(starts) != expected:
        raise ValueError("IJCAI paper block missing its numbered identity")
    records = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.start():end]
        title_match = re.search(
            r'<div\b[^>]*\bclass=["\'][^"\']*\btitle\b[^"\']*["\'][^>]*>(.*?)</div>',
            block, re.I | re.S,
        )
        authors_match = re.search(
            r'<div\b[^>]*\bclass=["\'][^"\']*\bauthors\b[^"\']*["\'][^>]*>(.*?)</div>',
            block, re.I | re.S,
        )
        details = []
        for href, label in re.findall(
            r'<a\b[^>]*\bhref=["\']([^"\']+)["\'][^>]*>(.*?)</a>', block, re.I | re.S
        ):
            if plain(label).casefold() == 'details':
                details.append(href)
        if not title_match or not authors_match or len(details) != 1:
            continue
        landing = urljoin('https://www.ijcai.org/', html.unescape(details[0])).rstrip('/')
        parsed = urlsplit(landing)
        if (parsed.scheme, parsed.hostname) != ('https', 'www.ijcai.org'):
            raise ValueError('IJCAI details link points outside the official site')
        if parsed.query or parsed.fragment or not re.fullmatch(rf'/proceedings/{year}/[1-9]\d*', parsed.path):
            raise ValueError('IJCAI details link has an invalid year or paper number')
        number = re.search(r'\bid=["\']paper(\d+)', match.group(0))[1]
        if int(parsed.path.rsplit('/', 1)[1]) != int(number):
            raise ValueError('IJCAI paper block and details identities differ')
        authors = [author for author in re.split(r'\s*,\s*', plain(authors_match[1])) if author]
        records.append(_raw(landing, plain(title_match[1]), authors, year))
    return _validate(records, len(starts))


def parse_kr(text, year):
    """Parse the official KR proceedings index without importing its preface."""
    starts = list(re.finditer(
        r'<div\b[^>]*\bclass=["\'][^"\']*track_paperinfo[^"\']*["\'][^>]*>', text, re.I
    ))
    blocks = [text[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(text)]
              for i, m in enumerate(starts)]
    records = []
    expected = 0
    for block in blocks:
        if not re.search(r'href=["\']/20\d{2}/[1-9]\d*/["\']', block):
            if "preface" in plain(block).casefold():
                continue
            raise ValueError("KR paper block missing its details link")
        expected += 1
        link = re.search(
            rf'<a\b[^>]*\bhref=["\'](/{year}/[1-9]\d*/)["\'][^>]*>(.*?)</a>',
            block, re.I | re.S,
        )
        authors_group = re.search(
            r'<ol\b[^>]*\bclass=["\'][^"\']*track_authors[^"\']*["\'][^>]*>(.*?)</ol>',
            block, re.I | re.S,
        )
        if not link or not authors_group:
            continue
        authors = [plain(value) for value in re.findall(r'<li\b[^>]*>(.*?)</li>', authors_group[1], re.I | re.S)]
        landing = urljoin('https://proceedings.kr.org/', link[1])
        records.append(_raw(landing, plain(link[2]), authors, year))
    return _validate(records, expected)


def parse_jmlr(text, year):
    volume = year - 1999
    if f"JMLR Volume {volume}" not in text:
        raise ValueError("JMLR volume/year mismatch")
    blocks = re.findall(r'<dl>(.*?)</dl>', text, re.S)
    records = []
    for block in blocks:
        title = re.search(r'<dt>(.*?)</dt>', block, re.S)
        authors = re.search(r'<b><i>(.*?)</i></b>', block, re.S)
        link = re.search(r"href=['\"](/papers/v\d+/[^'\"]+\.html)['\"]", block)
        if title and authors and link and re.search(rf',\s*{year}\.', block):
            records.append(_raw('https://jmlr.org' + link[1], plain(title[1]), plain(authors[1]).split(','), year))
    return _validate(records, len(blocks))


def parse_anthology(text, year, venue, collection):
    if '<!DOCTYPE' in text or '<!ENTITY' in text:
        raise ValueError("XML entities are not permitted")
    root = ET.fromstring(text)
    if root.tag != 'collection' or root.get('id') != collection:
        raise ValueError("Anthology collection mismatch")
    accepted = {'ACL': {'long', 'main'}, 'EMNLP': {'main'}, 'COLING': {'main'}, 'TACL': None, 'CL': None}[venue]
    records = []
    expected = 0
    for volume in root.findall('volume'):
        if accepted is not None and volume.get('id') not in accepted:
            continue
        if venue in ('TACL', 'CL') and volume.get('type') != 'journal':
            raise ValueError('Expected an Anthology journal volume')
        meta = volume.find('meta')
        if meta is None or meta.findtext('year') != str(year):
            raise ValueError("Anthology publication year mismatch")
        if meta.findtext('venue') not in {'ACL': {'acl'}, 'EMNLP': {'emnlp'}, 'COLING': ({'lrec'} if collection == '2024.lrec' and year == 2024 else {'coling'}), 'TACL': {'tacl'}, 'CL': {'cl'}}[venue]:
            raise ValueError("Anthology venue mismatch")
        for paper in volume.findall('paper'):
            expected += 1
            title = paper.find('title')
            authors = [' '.join(filter(None, [a.findtext('first'), a.findtext('last')])) for a in paper.findall('author')]
            abstract = paper.find('abstract')
            url = f"https://aclanthology.org/{collection}-{volume.get('id')}.{paper.get('id')}/"
            records.append(_raw(url, ''.join(title.itertext()) if title is not None else '', authors, year,
                                doi=paper.findtext('doi'), abstract=''.join(abstract.itertext()) if abstract is not None else None))
    return _validate(records, expected)

async def fetch_official_inventory(client, limiter, venue, year):
    """Read a supported publisher's complete volume, or return None if unsupported."""
    async def read(url):
        await limiter.acquire()
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()
        if not any(t in content_type for t in ('html', 'xml', 'text/plain', 'application/json')):
            raise ValueError('Unexpected official metadata content type')
        return response.text

    abbr = venue.abbr
    if abbr == 'TPAMI':
        from app.collectors.csdl import fetch_csdl_inventory
        return await fetch_csdl_inventory(read, year)
    if abbr in ('AAAI', 'ICAPS', 'JAIR'):
        from app.collectors.ojs import fetch_ojs_inventory
        return await fetch_ojs_inventory(read, abbr, year)
    if abbr == 'ICLR':
        return parse_iclr(await read(f'https://iclr.cc/static/virtual/data/iclr-{year}-orals-posters.json'), year)
    if abbr == 'ECCV':
        body = await read('https://www.ecva.net/papers.php')
        if f'papers/eccv_{year}/' in body:
            return parse_eccv(body, year)
        return parse_eccv_catalogue(await read(f'https://eccv.ecva.net/static/virtual/data/eccv-{year}-orals-posters.json'), year)
    if abbr == 'AAMAS':
        return parse_aamas(await read(f'https://www.ifaamas.org/Proceedings/aamas{year}/forms/contents.htm'), year)
    if abbr == 'IJCAI':
        return parse_ijcai(await read(f'https://www.ijcai.org/proceedings/{year}/'), year)
    if abbr == 'KR':
        return parse_kr(await read(f'https://proceedings.kr.org/{year}/'), year)
    if abbr == 'NeurIPS':
        body = await read(f'https://papers.nips.cc/paper_files/paper/{year}')
        volumes = neurips_main_volumes(body, year)
        if volumes:
            records = []
            for url in volumes:
                records.extend(parse_neurips(await read(url), year))
            return _validate(records, len(records))
        return parse_neurips(body, year)
    if abbr == 'JMLR':
        return parse_jmlr(await read(f'https://jmlr.org/papers/v{year - 1999}/'), year)
    if abbr in ('CVPR', 'ICCV'):
        return parse_cvf(await read(f'https://openaccess.thecvf.com/{abbr}{year}?day=all'), year, abbr)
    if abbr in ('ICML', 'UAI'):
        volumes = [v for v in pmlr_volumes(await read('https://proceedings.mlr.press/'), [year]) if v[0] == abbr]
        if not volumes and abbr == 'ICML':
            return parse_icml(await read(f'https://icml.cc/static/virtual/data/icml-{year}-orals-posters.json'), year)
        if len(volumes) != 1:
            raise ValueError('Official main volume not uniquely available in publisher index')
        url = volumes[0][2]
        return parse_pmlr(await read(url), year, url, abbr)
    if abbr in ('ACL', 'EMNLP', 'COLING', 'TACL', 'CL'):
        collection = f'{year}.{abbr.lower()}' if not (abbr == 'COLING' and year == 2024) else '2024.lrec'
        url = f'https://raw.githubusercontent.com/acl-org/acl-anthology/master/data/xml/{collection}.xml'
        return parse_anthology(await read(url), year, abbr, collection)
    return None

def parse_eccv(text, year):
    blocks = re.split(r'<dt class="ptitle">', text)[1:]
    records = []
    expected = len(re.findall(rf'href=[\"\']?papers/eccv_{year}/[^\s>\"\']+/html/[^\s>\"\']+', text))
    for block in blocks:
        link = re.search(r'<a href=[\"\']?(papers/eccv_' + str(year) + r'/[^\s>\"\']+/html/[^\s>\"\']+)[\"\']?[^>]*>(.*?)</a>', block, re.S)
        if not link:
            continue
        authors = re.search(r'</dt>\s*<dd>(.*?)</dd>', block, re.S)
        doi = re.search(r'https://link.springer.com/chapter/(10\.1007/[^\"\s<>]+)', block)
        if authors:
            records.append(_raw('https://www.ecva.net/' + link[1], plain(link[2]), plain(authors[1]).replace('*', '').split(','), year, doi=doi[1] if doi else None))
    from app.collectors.title_corrections import correct_catalogue_title
    return [correct_catalogue_title(raw) for raw in _validate(records, expected)]


def parse_aamas(text, year):
    base = f'https://www.ifaamas.org/Proceedings/aamas{year}/forms/contents.htm'
    sections = list(re.finditer(r'<a name="([^"]+)" id="[^"]+"></a>', text, re.I))
    records = []; expected = 0
    for i, section in enumerate(sections):
        # Invited keynotes and doctoral abstracts are not peer-reviewed papers.
        if section[1].upper() == 'TOP':
            continue
        body = text[section.end():sections[i + 1].start() if i + 1 < len(sections) else len(text)]
        header = plain(body.split('../pdfs/', 1)[0]).lower()
        if any(label in header for label in ('keynote', 'doctoral consortium', 'jaamas track')):
            continue
        expected += len(re.findall(r'href="\.\./pdfs/[A-Za-z0-9_-]+\.pdf"', body, re.I))
        for block in re.findall(r'<p\b[^>]*>(.*?)</p>', body, re.S | re.I):
            link = re.search(r'<a\b[^>]*href="(\.\./pdfs/[A-Za-z0-9_-]+\.pdf)"[^>]*>(.*?)</a>', block, re.S | re.I)
            if not link:
                continue
            # Each author occupies a separate <br> line; italic text is
            # affiliation metadata, not part of the person's identity.
            lines = re.split(r'<br\s*/?>', block, flags=re.I)[1:]
            authors = [plain(re.sub(r'<i\b[^>]*>.*?</i>', '', line, flags=re.S | re.I)) for line in lines]
            authors = [name for name in authors if name]
            if authors:
                records.append(_raw(urljoin(base, link[1]), plain(link[2]), authors, year))
    return _validate(records, expected)


def parse_iclr(text, year):
    return _parse_virtual_catalogue(text, year, 'ICLR')


def parse_icml(text, year, *, as_of=None):
    """ICML's official accepted catalogue when its PMLR volume is not yet indexed.

    Position papers are peer-reviewed proceedings papers according to ICML's
    official call; journal presentations and workshops are not ICML papers.
    Unlike a list of future acceptances, the catalogue must contain concluded conference
    events in the requested year (virtual posters may lack session times).
    """
    return _parse_virtual_catalogue(text, year, 'ICML', as_of=as_of or datetime.now(timezone.utc))


def parse_neurips_catalogue(text, year, *, as_of=None):
    """Concluded, peer-reviewed datasets/benchmarks and position-paper tracks."""
    return _parse_virtual_catalogue(text, year, 'NeurIPS', as_of=as_of or datetime.now(timezone.utc))


def _parse_virtual_catalogue(text, year, venue, *, as_of=None):
    """Official conference catalogue, excluding journal/blog/workshop tracks.

    Oral talks are repeat presentations, not additional papers. We require each
    to reference an included main-conference poster before dropping it.
    """
    data = json.loads(text)
    rows = data.get('results')
    if not isinstance(rows, list) or data.get('count') != len(rows) or data.get('next'):
        raise ValueError(f'Incomplete {venue} conference catalogue')
    sources = {f'https://openreview.net/group?id={venue}.cc/{year}/Conference'}
    if venue == 'ICML':
        sources.add(f'https://openreview.net/group?id=ICML.cc/{year}/Position_Paper_Track')
    if venue == 'NeurIPS':
        sources = {f'https://openreview.net/group?id=NeurIPS.cc/{year}/{track}'
                   for track in ('Datasets_and_Benchmarks_Track', 'Position_Paper_Track')}
    main = [r for r in rows if r.get('sourceurl') in sources and str(r.get('decision', '')).lower().startswith('accept')]
    if len({r['id'] for r in main}) != len(main):
        raise ValueError(f'Duplicate {venue} event identity')
    posters = {r['id']: r for r in main if r.get('eventtype') == 'Poster'}
    for row in main:
        if row.get('eventtype') == 'Oral':
            linked = any(pid in posters for pid in row.get('related_events_ids', []))
            if not linked and venue == 'NeurIPS':
                by_id = {r['id']: r for r in rows}
                for related in row.get('related_events_ids', []):
                    remote = by_id.get(related, {})
                    if remote.get('sourceurl') != 'cdmx-' + row['sourceurl'] + '-cdmx':
                        continue
                    for pid in remote.get('related_events_ids', []):
                        poster = posters.get(pid)
                        if not poster:
                            continue
                        names = lambda r: {a.get('fullname') for a in r.get('authors', [])}
                        if (remote.get('name') == row.get('name') == poster.get('name')
                                and names(remote) == names(row) == names(poster)
                                and row['id'] in remote.get('related_events_ids', [])
                                and related in poster.get('related_events_ids', [])):
                            linked = True
            if not linked:
                raise ValueError(f'{venue} oral has no verified main-conference poster')
        elif row.get('eventtype') != 'Poster':
            raise ValueError(f'Unknown {venue} publication event type')
    if as_of is not None:
        dated = [row for row in main if row.get('endtime')]
        if not dated:
            raise ValueError(f'{venue} catalogue has no verified event dates')
        for row in dated:
            try:
                ended = datetime.fromisoformat(row['endtime'])
            except ValueError as exc:
                raise ValueError(f'{venue} poster has no verified event date') from exc
            if ended.tzinfo is None or ended.year != year:
                raise ValueError(f'{venue} poster event year does not match catalogue')
            if ended > as_of:
                raise ValueError(f'{venue} conference event has not yet concluded')
    records = {}
    for row in posters.values():
        link = urlsplit(row.get('paper_url') or '')
        ids = parse_qs(link.query).get('id', [])
        if link.scheme != 'https' or link.hostname != 'openreview.net' or link.path != '/forum' or len(ids) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]+', ids[0]):
            raise ValueError(f'{venue} poster has no verified publication identifier')
        url = 'https://openreview.net/forum?id=' + ids[0]
        authors = [a['fullname'] for a in row.get('authors', []) if a.get('fullname')]
        raw = _raw(url, metadata_text(row.get('name', '')), authors, year, abstract=row.get('abstract'))
        if venue == 'NeurIPS':
            raw.extra['publication_track'] = row['sourceurl'].rsplit('/', 1)[-1]
        if url in records:
            previous = records[url]
            if previous.title != raw.title or set(previous.authors) != set(raw.authors):
                raise ValueError(f'Conflicting duplicate {venue} publication identifier')
        else:
            records[url] = raw
    return _validate(list(records.values()), len(records))


def parse_eccv_catalogue(text, year, *, as_of=None):
    """Concluded ECCV main conference with officially available paper links.

    ECVA's proceedings index can lag the conference portal. Require accepted
    posters, same-year concluded events and an official paper URL in metadata;
    do not fetch PDFs. Oral/spotlight events are repeat presentations, not papers.
    """
    as_of = as_of or datetime.now(timezone.utc)
    data = json.loads(text)
    rows = data.get('results')
    if not isinstance(rows, list) or data.get('count') != len(rows) or data.get('next'):
        raise ValueError('Incomplete ECCV conference catalogue')
    source = f'https://openreview.net/group?id=thecvf.com/ECCV/{year}/Conference'
    main = [row for row in rows if row.get('sourceurl') == source]
    if any(type(row.get('id')) is not int for row in main) or len({row['id'] for row in main}) != len(main):
        raise ValueError('Duplicate or invalid ECCV event identity')
    posters = {row['id']: row for row in main if row.get('eventtype') == 'Poster'
               and str(row.get('decision', '')).lower().startswith('accept')}
    for row in main:
        if row.get('eventtype') in ('Oral', 'Spotlight'):
            if not any(pid in posters for pid in row.get('related_events_ids', [])):
                raise ValueError('ECCV repeat presentation has no accepted poster')
        elif row.get('eventtype') != 'Poster':
            raise ValueError('Unknown ECCV publication event type')
        elif row['id'] not in posters and str(row.get('decision', '')).lower() not in ('reject', 'withdrawn'):
            raise ValueError('Unverified ECCV poster decision')
    records = []
    source_ids = set()
    for row in posters.values():
        source_id = row.get('sourceid')
        if type(source_id) is not int or source_id <= 0 or source_id in source_ids:
            raise ValueError('Duplicate or invalid ECCV paper identity')
        source_ids.add(source_id)
        route = f"/virtual/{year}/poster/{row['id']}"
        paper_url = f'https://media.eventhosts.cc/Conferences/ECCV{year}/pdfs/{source_id}.pdf'
        if row.get('virtualsite_url') != route or row.get('paper_pdf_url') != paper_url:
            raise ValueError('ECCV poster has no verified official paper link')
        try:
            ended = datetime.fromisoformat(row.get('endtime') or '')
        except (ValueError, TypeError) as exc:
            raise ValueError('ECCV poster has no verified event date') from exc
        if ended.tzinfo is None or ended.year != year:
            raise ValueError('ECCV poster event year does not match catalogue')
        if ended > as_of:
            raise ValueError('ECCV conference event has not yet concluded')
        authors = [a['fullname'] for a in row.get('authors', []) if a.get('fullname')]
        records.append(_raw('https://eccv.ecva.net' + route, metadata_text(row.get('name', '')), authors, year))
    return _validate(records, len(posters))


def publication_detail_doi(text, raw):
    """Use publisher citation metadata, never a DOI guessed from a URL."""
    class Citation(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.values = {}

        def handle_starttag(self, tag, attrs):
            data = dict(attrs)
            if tag == "meta":
                key = (data.get("name") or data.get("property") or "").casefold()
                self.values.setdefault(key, []).append(data.get("content", ""))

    from app.cleaning import normalize_title
    parser = Citation()
    parser.feed(text)
    titles = {normalize_title(metadata_text(t)) for t in parser.values.get("citation_title", [])}
    dois = {normalize_doi(d) for d in parser.values.get("citation_doi", [])}
    dois.discard(None)
    if titles != {normalize_title(metadata_text(raw.title))} or len(dois) != 1:
        raise ValueError("Publisher detail has no unique matching citation title and DOI")
    return dois.pop()
