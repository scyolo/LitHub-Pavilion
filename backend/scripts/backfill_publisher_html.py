"""Collect small official HTML indexes for CIDR, EDBT and Interspeech; no media downloads."""
import argparse
import asyncio
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.collectors.publisher_html_catalogs import SOURCES
from app.collectors.crossref import request_with_retry
from app.db import _make_engine
from app.models import Venue
from scripts.backfill_usenix import apply_records
from scripts.reconcile_papers import _backup

async def run(args):
    if not args.database.is_file():raise ValueError('Existing database required')
    args.output.mkdir(parents=True,exist_ok=True);path=args.output/'report.json'
    report={'started_at':datetime.now(timezone.utc).isoformat(),'pdf_downloads':0,'full_coverage_verified':False,'units':[]}
    if args.apply:report['backup']=str(_backup(args.database.resolve()))
    def save():
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    engine=_make_engine('sqlite:///'+args.database.resolve().as_posix())
    try:
        async with httpx.AsyncClient(timeout=60,follow_redirects=False) as client:
            for name in args.venue or SOURCES:
                template,parse=SOURCES[name]
                for year in range(2023,2027):
                    unit={'venue':name,'year':year,'status':'running','complete':False};report['units'].append(unit);save()
                    try:
                        url=template.format(year=year);file=args.output/(re.sub(r'[^A-Za-z0-9_-]','',name)+f'-{year}.html')
                        if file.exists():html=file.read_text(encoding='utf-8')
                        else:
                            response=await request_with_retry(client,url,attempts=4);response.raise_for_status()
                            if len(response.content)>20_000_000 or 'html' not in response.headers.get('content-type',''):raise ValueError('Unexpected publisher response')
                            html=response.text;file.write_text(html,encoding='utf-8')
                        records=parse(html,year)
                        unit.update(source=url,html_sha256=hashlib.sha256(html.encode()).hexdigest(),records=len(records))
                        if args.apply:
                            with Session(engine) as session:
                                venue=session.query(Venue).filter_by(abbr=name,type='conf').one()
                                if venue.ccf_level not in ('A','B'):raise ValueError('Non A/B source')
                                unit['counts']=apply_records(session,venue,records)
                        unit['status']='official_index_parsed'
                    except (httpx.HTTPError,ValueError,KeyError,TypeError,OSError,SQLAlchemyError) as error:unit.update(status='unresolved',error=f'{type(error).__name__}: {error}')
                    save();print(json.dumps(unit,ensure_ascii=False),flush=True);await asyncio.sleep(0.5)
    finally:engine.dispose()
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--venue',action='append',choices=list(SOURCES));p.add_argument('--apply',action='store_true');asyncio.run(run(p.parse_args()))
if __name__=='__main__':main()
