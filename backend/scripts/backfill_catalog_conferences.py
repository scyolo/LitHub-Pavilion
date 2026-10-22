"""Per-source, paged CCF conference metadata/link backfill. Never fetch PDFs.

Discovery results are candidates, not inventory completeness. Admit articles only
by an exact main-container name plus an explicit event year, preserving conflicts.
"""
import argparse
import asyncio
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.collectors.catalog_conferences import conference_year
from app.collectors.conference_registry import container_filter as container_filter
from app.collectors.conference_registry import discover_containers
from app.collectors.crossref import API, _fetch_inventory
from app.collectors.http_client import make_client
from app.db import _make_engine
from app.models import Paper, Venue
from app.ratelimit import AsyncTokenBucket
from app.services.catalog_backfill import apply_catalog_page
from app.services.tagging import load_rules, load_thresholds
from scripts.reconcile_papers import _backup

ROOT=Path(__file__).resolve().parents[2]


async def run(args):
    if not args.database.is_file():raise ValueError('Existing local database required')
    args.output.mkdir(parents=True,exist_ok=True)
    path=args.output/'report.json'
    previous=json.loads(path.read_text(encoding='utf-8')) if args.resume and path.is_file() else {}
    seeds={r['abbr']:r for r in csv.DictReader((ROOT/'seeds/venues.csv').open(encoding='utf-8-sig')) if r['type']=='conf' and r['ccf_level'] in ('A','B')}
    engine=_make_engine('sqlite:///'+args.database.resolve().as_posix())
    with Session(engine) as session:
        venues=session.query(Venue).filter(Venue.type=='conf',Venue.active==1).all()
        present={r[0] for r in session.query(Paper.venue_id).distinct()}
        requested=set(args.venue or []) | set(previous.get('requested_venues',[]))
        if args.all_missing: requested|={v.abbr for v in venues if v.id not in present}
        if requested-set(seeds): raise ValueError('Only configured CCF A/B conferences permitted')
        venues=[v for v in venues if v.abbr in requested]
        for v in venues:
            if (v.dblp_stream or '')!=seeds[v.abbr]['dblp_stream'] or v.name!=seeds[v.abbr]['name']:
                raise ValueError('Local source identity differs from catalog: '+v.abbr)
        session.expunge_all()
    report={'started_at':datetime.now(timezone.utc).isoformat(),'pdf_downloads':0,'applied':args.apply,
            'requested_venues':sorted(requested),'full_coverage_verified':False,'units':[]}
    if args.apply:report['backup']=str(_backup(args.database.resolve()))
    def save():
        temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    save();limiter=AsyncTokenBucket(1)
    try:
        async with make_client() as client:
            for venue in sorted(venues,key=lambda v:v.abbr):
                for year in range(args.year_from,args.year_to+1):
                    old=next((u for u in previous.get('units',[]) if u['venue']==venue.abbr and u['year']==year),None)
                    if old and old.get('status')=='registry_enumerated' and previous.get('applied')==args.apply:
                        report['units'].append(old);save();continue
                    unit={'venue':venue.abbr,'year':year,'complete':False,'status':'running','counts':{},'containers':[]}
                    report['units'].append(unit);save()
                    stats=Counter();seen=set()
                    try:
                        candidates, count = await discover_containers(client, venue, year, limiter)
                        unit['discovery_candidates'] = count
                        unit['containers']=[{'filter':f,'title':t} for f,t in candidates.items()]
                        if not candidates:
                            unit['status']='no_verified_container';save();continue
                        with Session(engine) as session:
                            rules,thresholds=load_rules(session),load_thresholds(session)
                            def on_page(label, page, count, total, records, *, seen=seen, venue=venue,
                                        year=year, stats=stats, rules=rules, thresholds=thresholds,
                                        unit=unit, session=session):
                                eligible=[]
                                for item in records:
                                    doi=item.get('DOI')
                                    if doi in seen:continue
                                    seen.add(doi)
                                    if conference_year(item,venue)==year:eligible.append(item)
                                    else:stats['excluded_identity_or_edition']+=1
                                if args.apply and eligible:
                                    result=apply_catalog_page(session,eligible,[year],rules,thresholds);stats.update(result['counts'])
                                    if result['conflicts']:
                                        with (args.output/'conflicts.jsonl').open('a',encoding='utf-8') as f:
                                            for conflict in result['conflicts']:f.write(json.dumps({'venue':venue.abbr,**conflict},ensure_ascii=False)+'\n')
                                elif not args.apply:stats['eligible']+=len(eligible)
                                unit['counts']=dict(stats);unit['page']={'number':page,'seen':count,'advertised':total};save()
                                print(json.dumps({'venue':venue.abbr,'year':year,'page':unit['page'],'counts':unit['counts']},ensure_ascii=False),flush=True)
                            for exact_filter,title in candidates.items():
                                await _fetch_inventory(client,API+'/works',title,max(2000,year-1),year+1,on_page=on_page,
                                                       max_pages=200,extra_filter=exact_filter)
                        unit['status']='partial' if stats['identity_conflicts'] else 'registry_enumerated'
                        unit['note']='All discovered exact containers enumerated; publisher-wide discovery completeness unverified'
                    except (httpx.HTTPError,ValueError,KeyError,TypeError,OSError,SQLAlchemyError) as error:
                        unit.update(status='partial' if seen else 'failed',error=f'{type(error).__name__}: {error}')
                    save();print(json.dumps(unit,ensure_ascii=False),flush=True)
    finally:engine.dispose()
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--venue',action='append');parser.add_argument('--all-missing',action='store_true')
    parser.add_argument('--year-from',type=int,default=2023);parser.add_argument('--year-to',type=int,default=2026)
    parser.add_argument('--resume',action='store_true');parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not args.venue and not args.all_missing:parser.error('Choose --venue or --all-missing')
    if not 2000<=args.year_from<=args.year_to<=datetime.now(timezone.utc).year:parser.error('Invalid publication-year range')
    asyncio.run(run(args))


if __name__=='__main__':main()
