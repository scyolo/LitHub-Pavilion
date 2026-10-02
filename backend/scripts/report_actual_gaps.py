"""Separate proven absent publications, existing metadata issues and unknowns.
Read-only; this report never turns a failed metadata match into a missing paper.
"""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

from app.cleaning import normalize_title
from app.collectors.acm_proceedings import match_official_track
from app.collectors.crossref import metadata_text
from app.services.publication_admission import admission_reason
from scripts.audit_coverage_ledger import ADAPTERS


def classify_verified(raw, candidates, venue):
    if not candidates:
        return 'verified_identity_absent_from_database'
    if len(candidates) != 1:
        return 'existing_identity_conflict'
    paper = SimpleNamespace(**candidates[0])
    if paper.venue_id != venue.id or paper.year != raw.year or paper.title_norm != normalize_title(raw.title):
        return 'existing_metadata_difference'
    if admission_reason(paper, venue):
        return 'existing_not_publicly_admitted'
    return 'existing_publication'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    database = args.database.resolve()
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
    papers = [dict(row) for row in db.execute('SELECT * FROM papers')]
    venues = {row['abbr']: SimpleNamespace(**dict(row)) for row in db.execute('SELECT * FROM venues WHERE active=1')}
    by_doi, by_title = defaultdict(list), defaultdict(list)
    public, abstracts = Counter(), Counter()
    for paper in papers:
        if paper['doi']:
            by_doi[paper['doi']].append(paper)
        by_title[paper['title_norm']].append(paper)
        venue = next((v for v in venues.values() if v.id == paper['venue_id']), None)
        if venue and admission_reason(SimpleNamespace(**paper), venue) is None:
            public[(venue.abbr, paper['year'])] += 1
            abstracts[(venue.abbr, paper['year'])] += not bool((paper['abstract'] or '').strip())
    # Author-content verification is a separate gate from paper presence.
    stored_author_conflicts = set()
    ledger_file = args.evidence / 'current-identity-ledger.json'
    if ledger_file.is_file():
        ledger = json.loads(ledger_file.read_text('utf8'))
        for unit in ledger.get('units', []):
            scope = unit.get('selected_research_scope') or {}
            for issue in scope.get('missing_or_conflicting', []):
                if issue.get('reason') == 'author_identity_mismatch':
                    stored_author_conflicts.add(issue['doi'])
    units, details = [], []
    for (abbr, year), (filename, parse) in ADAPTERS.items():
        unit = {'venue': abbr, 'year': year, 'scope': 'official selected research list, not all tracks',
                'source_file': filename, 'public_records_in_venue_year': public[(abbr, year)]}
        try:
            official = parse(args.evidence)
            inventory = json.loads((args.evidence / f"inventory-{abbr.replace(' ', '_')}-{year}.json").read_text('utf8'))
            verified, unresolved = match_official_track(inventory, official)
            statuses = Counter()
            for raw in verified:
                found = by_doi.get(raw.doi, [])
                # A different/omitted DOI but same title is an identity review,
                # not sufficient evidence of a truly absent publication.
                if not found and by_title.get(normalize_title(raw.title)):
                    status = 'title_exists_doi_identity_unresolved'
                    found = by_title[normalize_title(raw.title)]
                else:
                    status = classify_verified(raw, found, venues[abbr])
                if status == 'existing_publication' and raw.doi in stored_author_conflicts:
                    status = 'existing_author_metadata_conflict'
                statuses[status] += 1
                if status != 'existing_publication':
                    details.append({'venue': abbr, 'year': year, 'status': status, 'title': raw.title,
                                    'doi': raw.doi, 'database_ids': [p['id'] for p in found],
                                    'topic_eligibility': 'not_semantically_verified'})
            index = defaultdict(list)
            for item in inventory['items']:
                index[normalize_title(metadata_text(item['title'][0]))].append(item)
            for row in unresolved:
                title = normalize_title(row['title'])
                existing = by_title.get(title, [])
                hits = index.get(title, [])
                for item in hits:
                    existing = existing + by_doi.get(item['DOI'].lower(), [])
                status = 'unresolved_metadata_with_existing_candidate' if existing else 'unresolved_identity_not_proven_missing'
                statuses[status] += 1
                details.append({'venue': abbr, 'year': year, 'status': status, 'title': row['title'],
                                'reason': row['reason'], 'database_ids': sorted({p['id'] for p in existing}),
                                'publisher_candidate_dois': [i['DOI'] for i in hits],
                                'topic_eligibility': 'not_semantically_verified'})
            unit.update(official_expected=len(official), counts=dict(statuses))
            assert sum(statuses.values()) == len(official)
        except (ValueError, OSError, KeyError) as exc:
            unit.update(error=str(exc), official_expected=None, counts={})
        units.append(unit)
    all_counts = Counter()
    for unit in units:
        all_counts.update(unit['counts'])
    known = set(ADAPTERS)
    unaudited = [{'venue': abbr, 'year': year, 'public_records': public[(abbr, year)],
                  'missing_abstracts': abstracts[(abbr, year)],
                  'status': 'not_reconciled_by_this_report; other evidence may exist'}
                 for abbr in venues for year in range(2023, 2027) if (abbr, year) not in known]
    report = {'database_read_only': True, 'configured_sources': len(venues), 'years': [2023,2024,2025,2026],
              'reconciled_selected_lists': len(units), 'counts': dict(all_counts), 'units': units,
              'details': details, 'other_source_year_units': unaudited,
              'target_topic_missing_total': None, 'full_coverage_proven': False,
              'limitations': ['Verified absence is limited to identity-confirmed records in these selected lists.',
                             'Unresolved author/title differences are not counted as missing publications.',
                             'Source/year public counts include all admitted topics; not a count of the nine target directions.',
                             'Missing abstract counts are not missing-paper counts.',
                             'No semantic review of missing candidates or independent CCF grade audit is implied.']}
    db.close()
    output = args.evidence / 'actual-gap-report.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    lines = ['# 实际覆盖差异：缺论文与元数据问题分开', '',
             '本报告只读核对当前数据库。指定九个方向究竟缺多少篇：**尚不能确认**。',
             '以下统计仅针对已接入的官方研究名单，不代表全部来源、全部分轨或方向全量。', '',
             '| 来源 | 年份 | 官方名单条数 | 已存在且公开（非逐篇内容认证） | 确认身份且库中不存在 | 已存在但状态/元数据待查 | 身份未定、不能算缺失 |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for u in units:
        c = u['counts']
        existing_issues = sum(v for k,v in c.items() if k not in ('existing_publication','verified_identity_absent_from_database','unresolved_identity_not_proven_missing'))
        lines.append(f"| {u['venue']} | {u['year']} | {u['official_expected']} | {c.get('existing_publication',0)} | {c.get('verified_identity_absent_from_database',0)} | {existing_issues} | {c.get('unresolved_identity_not_proven_missing',0)} |")
    lines += ['', '## 解释', '', '“库中不存在”还没有经过指定方向语义复核，不能直接称为你的方向缺失量。',
              '“身份未定”可能是题名变更、作者差异、页面错误，也可能是真缺失，需要逐篇证据；绝不直接累加为缺失。',
              f'另有 {len(unaudited)} 个来源—年份单元未由本报告完成对账；不等于没有论文或没有其他采集证据。',
              '所有具体题名、DOI 候选和数据库记录编号见同目录 actual-gap-report.json。',
              '网站仍未更新；本报告没有执行采集、入库、推送或发布。']
    (args.evidence / 'ACTUAL_GAPS.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({'counts':dict(all_counts),'selected_lists':len(units),'other_units':len(unaudited),'report':str(output)},ensure_ascii=False))


if __name__ == '__main__':
    main()
