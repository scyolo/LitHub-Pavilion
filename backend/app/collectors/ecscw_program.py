"""Explicit ECSCW journal-paper programmes; no exploratory papers or PDF reads."""

import re

from app.collectors.publisher_toc import _raw
from app.collectors.usenix_catalog import Tree


def _lines(node):
    if isinstance(node, str):
        return node
    if node.tag == 'br':
        return '\n'
    return ''.join(_lines(child) for child in node.children)


def parse_journal_program(html, year):
    if year not in (2023, 2025):
        raise ValueError('Unsupported ECSCW programme year')
    tree = Tree(); tree.feed(html)
    if not any(re.search(r'(?:ECSCW|ESCSW)\s*' + str(year), n.text())
               for n in tree.root.find(lambda n: n.tag in ('title', 'h1', 'h2'))):
        raise ValueError('ECSCW programme year mismatch')
    source = f'https://ecscw.eusset.eu/{year}/' + ('journal-papers-program/' if year == 2023 else 'index.php/program/')
    bodies = tree.root.find(lambda n: n.has_class('entry-content'))
    if len(bodies) > 1:
        raise ValueError('Ambiguous ECSCW programme body')
    body = bodies[0] if bodies else tree.root
    active = year == 2023
    groups, current = [], None
    for node in body.find(lambda n: n.tag in ('h1', 'h5', 'p')):
        text = node.text().strip()
        if year == 2025 and node.tag == 'h1':
            if active and text != 'Journal Papers':
                break
            active = text == 'Journal Papers'
            continue
        if not active:
            continue
        titles = node.find(lambda n: n.tag == 'strong')
        title = text if year == 2023 and node.tag == 'h5' else (
            titles[0].text().strip() if year == 2025 and node.tag == 'p'
            and len(titles) == 1 and text == titles[0].text().strip() else None
        )
        if title:
            current = {'title': title, 'authors': [], 'abstract': [], 'doi': None}
            groups.append(current)
            continue
        if current is None or node.tag != 'p':
            continue
        if not current['authors']:
            if year == 2023:
                if text.startswith(('Abstract', 'http')):
                    continue
                current['authors'] = [line.split(',', 1)[0].strip() for line in _lines(node).splitlines() if line.strip()]
            else:
                authors = node.find(lambda n: n.tag == 'em')
                if len(authors) == 1 and text == authors[0].text().strip():
                    current['authors'] = [name.strip() for name in re.split(r',|\band\b', text) if name.strip()]
            continue
        links = node.find(lambda n: n.tag == 'a' and n.attrs.get('href'))
        if text.startswith('http'):
            for link in links:
                doi = re.search(r'10\.1007/s10606-[0-9-]+', link.attrs['href'])
                if doi:
                    current['doi'] = doi[0]
            continue
        if text:
            current['abstract'].append(text.removeprefix('Abstract').strip())
    records = []
    for group in groups:
        if not group['title'] or not group['authors']:
            raise ValueError('Incomplete ECSCW journal-paper title/author pair')
        raw = _raw(source, group['title'], group['authors'], year,
                   doi=group['doi'], abstract=' '.join(group['abstract']) or None)
        raw.extra['provenance'] = 'official_conference_list'
        records.append(raw)
    if not records or len({r.title for r in records}) != len(records):
        raise ValueError('Empty or duplicate ECSCW journal programme')
    return records
