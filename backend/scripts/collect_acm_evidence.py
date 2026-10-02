"""Collect ACM metadata evidence to disk, without admitting unverified tracks.

Run after exact container discovery; never write a database or publish a snapshot.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx

from app.collectors.acm_proceedings import fetch_inventory
from app.config import settings


async def run(args):
    directory = args.evidence.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.registry:
        registry = json.loads(args.registry.read_text(encoding='utf8'))
        for unit in registry['units']:
            if unit['venue'] not in {'SIGIR', 'WWW', 'ACM MM', 'WSDM', 'CIKM'} or not isinstance(unit['year'], int):
                raise ValueError('Invalid registered conference unit')
            path = directory / (f"container-{unit['venue'].replace(' ', '_')}-{unit['year']}.json")
            path.write_text(json.dumps({'venue': unit['venue'], 'year': unit['year'],
                'requested_container': unit['title'], 'verified': True,
                'parent_doi': unit['parent_doi'], 'other_parent_dois': unit.get('other_parent_dois', [])}, ensure_ascii=False), encoding='utf8')
    for path in sorted(directory.glob('container-*.json')):
        discovery = json.loads(path.read_text(encoding='utf8'))
        if not discovery.get('verified'):
            continue
        samples = discovery.get('items', [])
        parents = ({discovery['parent_doi']} if discovery.get('parent_doi') else
                   {item['DOI'].lower().rsplit('.', 1)[0] for item in samples})
        if len(parents) != 1:
            print(json.dumps({'unit': path.name, 'status': 'ambiguous_parent'}), flush=True)
            continue
        target = directory / ('inventory-' + path.name.removeprefix('container-'))
        if target.exists():
            cached = json.loads(target.read_text(encoding='utf8'))
            if (cached.get('doi_inventory_complete') and cached.get('container') == discovery['requested_container']
                    and cached.get('parent', {}).get('DOI') in parents
                    and set(cached.get('other_parent_partitions', {})) == set(discovery.get('other_parent_dois', []))):
                continue
        report = {'venue': discovery['venue'], 'year': discovery['year'],
                  'doi_inventory_complete': False, 'full_track_coverage_verified': False,
                  'track_status': 'unverified', 'database_modified': False}
        try:
            async with httpx.AsyncClient(timeout=45, follow_redirects=False, trust_env=False,
                                         headers={'User-Agent': settings.effective_user_agent}) as client:
                def save_page(page, rows, count, total):
                    data = json.dumps(rows, ensure_ascii=False).encode('utf8')
                    page_path = directory / (target.stem + f'-page-{page}.json')
                    page_path.write_bytes(data)
                    print(json.dumps({'unit': target.stem, 'page': page, 'received': count, 'expected': total,
                                      'sha256': hashlib.sha256(data).hexdigest()}), flush=True)
                inventory = await asyncio.wait_for(fetch_inventory(client, discovery['requested_container'],
                    discovery['year'], parents.pop(), on_page=save_page,
                    other_parent_dois=discovery.get('other_parent_dois', [])), timeout=args.timeout)
                report.update(inventory)
        except (httpx.HTTPError, ValueError, TimeoutError, KeyError) as exc:
            report.update(error=type(exc).__name__ + ': ' + str(exc)[:400])
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps({key: value for key, value in report.items() if key not in ('items', 'rejected', 'parent', 'other_parent_partitions')}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--registry', type=Path, help='Previously verified parent DOI registry; every parent is revalidated online')
    args = parser.parse_args()
    if (not args.evidence.is_dir() and not args.registry) or args.timeout < 1:
        parser.error('Existing evidence directory and positive timeout required')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
