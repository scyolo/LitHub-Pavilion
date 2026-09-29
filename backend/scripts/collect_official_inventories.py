"""Import complete official main-volume inventories; no PDFs, metadata only.

Official URLs are durable publisher identities (no fabricated DOI/DBLP keys).
Retain old ids and arXiv links when exact titles AND author sets verify a match.
Missing/failed volumes and identity conflicts remain explicit in the report.
"""
import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from app.collectors.publisher_toc import parse_aamas, parse_eccv, parse_eccv_catalogue, parse_anthology, parse_cvf, parse_jmlr, parse_iclr, parse_icml, parse_ijcai, parse_kr, parse_neurips, neurips_main_volumes, parse_pmlr, pmlr_volumes
from app.collectors.ojs import BASES, fetch_ojs_inventory
from app.collectors.csdl import index_url, fetch_csdl_inventory
from app.config import settings
from app.db import _make_engine, db_file_path
from app.models import Paper, Venue, utcnow_iso
from app.collectors.editions import publication_schedule
from scripts.reconcile_papers import _backup
from app.services.publisher_import import apply_records


# The report records non-runnable years explicitly so a missing page is not
# mistaken for a failed request or an empty proceedings volume.
def _schedule_unit(venue, year, url, kind, units, deferred):
    decision = publication_schedule(venue, year)
    entry = {
        'venue': venue, 'year': year, 'url': url,
        'inventory_complete': False,
    }
    if decision['status'] == 'scheduled':
        units.append((venue, year, url, kind))
    else:
        entry.update(status=decision['status'], reason=decision['reason'])
        deferred.append(entry)


def _official_units(years):
    units, deferred = [], []
    for year in years:
        _schedule_unit('TPAMI', year, index_url(year), 'csdl', units, deferred)
        for abbr, base in BASES.items():
            _schedule_unit(abbr, year, base + 'issue/archive', 'ojs', units, deferred)
        _schedule_unit('ICLR', year, f'https://iclr.cc/static/virtual/data/iclr-{year}-orals-posters.json', 'iclr', units, deferred)
        _schedule_unit('AAMAS', year, f'https://www.ifaamas.org/Proceedings/aamas{year}/forms/contents.htm', 'aamas', units, deferred)
        _schedule_unit('IJCAI', year, f'https://www.ijcai.org/proceedings/{year}/', 'ijcai', units, deferred)
        _schedule_unit('KR', year, f'https://proceedings.kr.org/{year}/', 'kr', units, deferred)
        _schedule_unit('ECCV', year, 'https://www.ecva.net/papers.php', 'eccv', units, deferred)
        _schedule_unit('NeurIPS', year, f'https://papers.nips.cc/paper_files/paper/{year}', 'neurips', units, deferred)
        _schedule_unit('JMLR', year, f'https://jmlr.org/papers/v{year - 1999}/', 'jmlr', units, deferred)
        for abbr in ('CVPR', 'ICCV'):
            _schedule_unit(abbr, year, f'https://openaccess.thecvf.com/{abbr}{year}?day=all', 'cvf', units, deferred)
        for abbr in ('ACL', 'EMNLP', 'COLING', 'TACL', 'CL'):
            collection = f'{year}.{abbr.lower()}' if not (abbr == 'COLING' and year == 2024) else '2024.lrec'
            _schedule_unit(abbr, year, f'https://raw.githubusercontent.com/acl-org/acl-anthology/master/data/xml/{collection}.xml', 'anthology', units, deferred)
    return units, deferred


async def run(args):
    path = args.database.resolve(); output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report = {'started_at': utcnow_iso(), 'backup': str(_backup(path)), 'scope': 'official publisher main proceedings; configured A/B venues', 'units': [], 'pdf_downloads': 0, 'full_collection_verified': False}
    target = output / f'official-inventory-{stamp}.json'
    engine = _make_engine('sqlite:///' + path.as_posix())
    years = range(args.year_from, args.year_to + 1)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers={'User-Agent': settings.effective_user_agent}) as client:
        async def read(url):
            if '.pdf' in url.lower():
                raise ValueError('PDF requests forbidden')
            cache = output / ('toc-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.txt')
            if cache.is_file() and not args.refresh:
                return cache.read_text('utf8')
            await asyncio.sleep(0.5)
            for attempt in range(3):
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2 ** attempt)
            if not any(t in response.headers.get('content-type', '').lower() for t in ('html', 'xml', 'text/plain', 'application/json')):
                raise ValueError('Unexpected inventory content type')
            cache.write_text(response.text, encoding='utf8')
            return response.text

        units, deferred_units = _official_units(years)
        if not args.venues or set(args.venues) & {'ICML', 'UAI'}:
            try:
                index = await read('https://proceedings.mlr.press/')
                volumes = pmlr_volumes(index, years)
                units.extend((*v, 'pmlr') for v in volumes)
                for abbr in ('ICML', 'UAI'):
                    for year in years:
                        if not any(v[:2] == (abbr, year) for v in volumes):
                            if abbr == 'ICML':
                                units.append((abbr, year, f'https://icml.cc/static/virtual/data/icml-{year}-orals-posters.json', 'icml'))
                            else:
                                report['units'].append({'venue': abbr, 'year': year, 'inventory_complete': False, 'status': 'official_unavailable', 'reason': 'No main volume in publisher index at collection time'})
            except Exception as exc:
                report['units'].append({'venue': 'ICML/UAI', 'inventory_complete': False, 'error': str(exc)[:300]})
        try:
            with Session(engine) as session:
                venues = {v.abbr: v for v in session.query(Venue).filter(Venue.active == 1, Venue.ccf_level.in_(('A', 'B'))).all()}
                for deferred in deferred_units:
                    if deferred['venue'] in venues and (not args.venues or deferred['venue'] in args.venues):
                        report['units'].append(dict(deferred))
                        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
                for abbr, year, url, kind in units:
                    if abbr not in venues or (args.venues and abbr not in args.venues):
                        continue
                    entry = {'venue': abbr, 'year': year, 'url': url, 'inventory_complete': False}
                    try:
                        body = await read(url)
                        if kind == 'ojs': records = await fetch_ojs_inventory(read, abbr, year)
                        elif kind == 'csdl': records = await fetch_csdl_inventory(read, year)
                        elif kind == 'iclr': records = parse_iclr(body, year)
                        elif kind == 'icml': records = parse_icml(body, year)
                        elif kind == 'aamas': records = parse_aamas(body, year)
                        elif kind == 'ijcai': records = parse_ijcai(body, year)
                        elif kind == 'kr': records = parse_kr(body, year)
                        elif kind == 'eccv':
                            if f'papers/eccv_{year}/' in body:
                                records = parse_eccv(body, year)
                            else:
                                entry['url'] = f'https://eccv.ecva.net/static/virtual/data/eccv-{year}-orals-posters.json'
                                records = parse_eccv_catalogue(await read(entry['url']), year)
                        elif kind == 'neurips':
                            volumes = neurips_main_volumes(body, year)
                            records = []
                            for volume_url in volumes:
                                records.extend(parse_neurips(await read(volume_url), year))
                            if not volumes:
                                records = parse_neurips(body, year)
                        elif kind == 'cvf': records = parse_cvf(body, year, abbr)
                        elif kind == 'jmlr': records = parse_jmlr(body, year)
                        elif kind == 'pmlr': records = parse_pmlr(body, year, url, abbr)
                        else: records = parse_anthology(body, year, abbr, url.rsplit('/', 1)[1][:-4])
                        total_records = len(records)
                        already_linked = 0
                        if args.missing_only:
                            existing = {key for key, in session.query(Paper.publisher_key).filter(Paper.publisher_key.is_not(None))}
                            pending = [raw for raw in records if raw.extra['publisher_key'] not in existing]
                            already_linked = len(records) - len(pending)
                            records = pending
                        entry.update(records=total_records, already_linked=already_linked, inventory_complete=True, **apply_records(session, records, venues[abbr]))
                    except (ValueError, httpx.HTTPError) as exc:
                        session.rollback()
                        entry['error'] = type(exc).__name__ + ': ' + str(exc)[:300]
                    report['units'].append(entry)
                    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
                    print(json.dumps({k: v for k, v in entry.items() if k not in ('changes', 'conflicts', 'associations')}, ensure_ascii=False), flush=True)
            with engine.connect() as c:
                report['paper_count'] = c.exec_driver_sql('SELECT count(*) FROM papers').scalar()
                report['quick_check'] = c.exec_driver_sql('PRAGMA quick_check').scalar()
        finally:
            engine.dispose()
            report['finished_at'] = utcnow_iso()
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
            print(json.dumps({'report': str(target)}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=db_file_path())
    parser.add_argument('--output', type=Path, default=Path('artifacts') / ('publication-audit-' + datetime.now(timezone.utc).strftime('%Y%m%d')))
    parser.add_argument('--year-from', type=int, default=settings.startup_year_from)
    parser.add_argument('--year-to', type=int, default=settings.startup_years[-1])
    parser.add_argument('--missing-only', action='store_true', help='Skip already-linked official identities; preserve total inventory count in report')
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--venues', nargs='*')
    args = parser.parse_args()
    if not 2000 <= args.year_from <= args.year_to <= 2100:
        parser.error('Invalid publication years')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
