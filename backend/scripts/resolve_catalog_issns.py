"""Fill only missing CCF journal ISSNs using unique exact Crossref registry names.

Writes evidence first. Ambiguous, approximate, or unmatched names are not applied.
"""
import argparse
import asyncio
import csv
import json
import re
from pathlib import Path
from app.cleaning import normalize_title
from app.collectors.http_client import make_client
from app.ratelimit import AsyncTokenBucket

ROOT=Path(__file__).resolve().parents[2]


def identity_title(value):
    return normalize_title(value).removeprefix('the ')


def exact_identity(name, items):
    matches=[item for item in items if identity_title(item.get('title','')) == identity_title(name)]
    if len(matches) != 1:
        return None
    item=matches[0]
    issns=sorted({issn for issn in item.get('ISSN',[]) if re.fullmatch(r'\d{4}-\d{3}[\dX]',issn)})
    return {'title':item['title'],'issns':issns,'issn':issns[0]} if issns else None


async def run(args):
    rows=list(csv.DictReader(args.seeds.open(encoding='utf-8-sig',newline='')))
    report={'source':'https://api.crossref.org/journals','applied':args.apply,'units':[]}
    limiter=AsyncTokenBucket(1)
    async with make_client() as client:
        for row in rows:
            if row['type']!='journal' or row['ccf_level'] not in ('A','B') or row['issn']:
                continue
            unit={'venue':row['abbr'],'catalog_name':row['name']}
            try:
                await limiter.acquire()
                response=await client.get(report['source'],params={'query':row['name'],'rows':20})
                response.raise_for_status()
                match=exact_identity(row['name'],response.json()['message']['items'])
                unit.update(status='verified' if match else 'no_unique_exact_identity',identity=match)
                if match and args.apply: row['issn']=match['issn']
            except Exception as error:
                unit.update(status='failed',error=type(error).__name__)
            report['units'].append(unit)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(unit,ensure_ascii=False),flush=True)
    if args.apply:
        # Re-read to avoid overwriting unrelated concurrent source edits.
        updates={u['venue']:u['identity']['issn'] for u in report['units'] if u['status']=='verified'}
        current=list(csv.DictReader(args.seeds.open(encoding='utf-8-sig',newline='')))
        for row in current:
            if not row['issn'] and row['abbr'] in updates: row['issn']=updates[row['abbr']]
        with args.seeds.with_suffix('.csv.tmp').open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(current[0]));writer.writeheader();writer.writerows(current)
        args.seeds.with_suffix('.csv.tmp').replace(args.seeds)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds',type=Path,default=ROOT/'seeds/venues.csv')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    asyncio.run(run(parser.parse_args()))


if __name__=='__main__': main()
