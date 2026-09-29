import json
from pathlib import Path

from scripts.audit_publications import build_audit, latest_entries


def test_latest_attempt_replaces_old_failure_and_old_success(tmp_path):
    for name, complete in [('001', False), ('002', True)]:
        (tmp_path / f'official-inventory-{name}.json').write_text(json.dumps({'units': [{'venue': 'ICLR', 'year': 2024, 'inventory_complete': complete}]}), encoding='utf-8')
    values = latest_entries(tmp_path, 'official-inventory-*.json', 'units', lambda e: (e['venue'], e['year']))
    assert values[('ICLR', 2024)]['inventory_complete']
    (tmp_path / 'official-inventory-003.json').write_text(json.dumps({'units': [{'venue': 'ICLR', 'year': 2024, 'inventory_complete': False}]}), encoding='utf-8')
    assert not latest_entries(tmp_path, 'official-inventory-*.json', 'units', lambda e: (e['venue'], e['year']))[('ICLR', 2024)]['inventory_complete']


def test_audit_read_only_counts_arxiv_oa_and_date_errors(db, engine, sample_paper, tmp_path):
    sample_paper.oa_url = 'https://arxiv.org/abs/2401.12345'
    sample_paper.note = 'Verified publisher metadata: Crossref DOI ' + sample_paper.doi
    sample_paper.publication_date = '2023-01-01'
    db.commit()
    path = Path(engine.url.database)
    original = path.read_bytes()
    report = build_audit(path, tmp_path / 'no-reports', range(2023, 2025))
    assert report['paper_count'] == 1 and report['without_direction'] == 1
    assert report['arxiv_with_publisher_evidence'] == report['arxiv_link_without_unique_id'] == 1
    assert report['date_issue_counts'] == {'year_mismatch': 1}
    assert report['fts_integrity'].startswith('ok') and report['foreign_key_errors'] == []
    assert report['full_collection_verified'] is False
    assert path.read_bytes() == original
    db.expire_all()
    assert sample_paper.publication_date == '2023-01-01'  # audit never auto-repairs


def test_complete_crossref_index_is_not_global_coverage(db, engine, sample_paper, tmp_path):
    cache = tmp_path / 'source.jsonl'
    # Intentionally empty but exhausted index cannot prove a complete venue.
    cache.write_text('', encoding='utf-8')
    (tmp_path / 'publisher-repair-001.json').write_text(json.dumps({'prefixes': [{'prefix': 'test', 'cache': str(cache), 'inventory_complete': True, 'records': 0}]}), encoding='utf-8')
    report = build_audit(Path(engine.url.database), tmp_path, range(2024, 2025), check_fts=False)
    assert report['crossref_sources'][0]['inventory_complete']
    assert report['coverage'][0]['status'] == 'not_verified'
    assert not report['full_collection_verified']


def test_off_cycle_year_is_reported_as_suspicious_not_silently_fixed(db, engine, sample_venue, sample_paper, tmp_path):
    sample_venue.abbr = 'ICCV'
    sample_paper.year = 2024
    db.commit()
    report = build_audit(Path(engine.url.database), tmp_path, range(2024, 2025), check_fts=False)
    assert report['unscheduled_year_record_count'] == 1
    assert report['unscheduled_year_records'][0]['id'] == sample_paper.id
    assert report['coverage'][0]['status'] == 'not_scheduled_by_adapter'
    db.expire_all()
    assert sample_paper.year == 2024


def test_crossref_title_difference_is_reported_separately_from_identity_coverage(db,engine,sample_paper,sample_venue,tmp_path):
    sample_venue.abbr = 'AAAI'
    sample_paper.doi = '10.1609/aaai.v38i1.12345'
    db.commit()
    item = {'DOI': sample_paper.doi, 'title': ['Different publisher title'],
            'type': 'proceedings-article', 'published': {'date-parts': [[2024]]},
            'container-title': ['Proceedings of the AAAI Conference on Artificial Intelligence']}
    cache = tmp_path / 'crossref.jsonl'
    cache.write_text(json.dumps(item)+'\n',encoding='utf-8')
    (tmp_path/'publisher-repair-001.json').write_text(json.dumps({'prefixes':[
        {'prefix':'10.1609','cache':str(cache),'inventory_complete':True,'records':1}]}),encoding='utf-8')
    result = build_audit(Path(engine.url.database),tmp_path,range(2024,2025),check_fts=False)
    assert result['crossref_identity_missing_count'] == 0
    assert result['crossref_title_mismatch_count'] == 1
    assert result['coverage'][0]['crossref_title_mismatches'][0]['id'] == sample_paper.id
    assert not result['full_collection_verified']


def test_joint_ecai_edition_is_not_a_second_inventory_or_full_coverage(db, engine, sample_venue, tmp_path):
    sample_venue.abbr = 'ECAI'
    db.commit()
    report = build_audit(Path(engine.url.database), tmp_path, range(2026, 2027), check_fts=False)
    unit = report['coverage'][0]
    assert unit['status'] == 'joint_edition'
    assert unit['joint_edition']['canonical_venue'] == 'IJCAI'
    assert unit['joint_edition']['canonical_stored'] == 0
    assert not report['full_collection_verified']


def test_joint_edition_does_not_hide_existing_alias_records(db, engine, sample_venue, sample_paper, tmp_path):
    sample_venue.abbr = 'ECAI'
    sample_paper.year = 2026
    db.commit()
    report = build_audit(Path(engine.url.database), tmp_path, range(2026, 2027), check_fts=False)
    assert report['coverage'][0]['status'] == 'joint_edition_requires_review'
    db.expire_all()
    assert sample_paper.year == 2026


def test_corrected_older_publications_remain_visible_outside_configured_range(db, engine, sample_paper, tmp_path):
    sample_paper.year = 2022
    db.commit()
    report = build_audit(Path(engine.url.database), tmp_path, range(2023, 2027), check_fts=False)
    assert report['paper_count'] == 1
    assert report['outside_configured_years'][0]['id'] == sample_paper.id
    assert report['outside_configured_years'][0]['year'] == 2022


def test_accessible_program_is_not_a_verified_publication_inventory(db, engine, sample_venue, tmp_path):
    sample_venue.abbr = 'ICRA'
    db.commit()
    (tmp_path / 'inventory-assessment-001.json').write_text(json.dumps({'units': [
        {'venue': 'ICRA', 'year': 2026, 'status': 'official_program_only',
         'program_records': 2951, 'publication_inventory_verified': False}]}), encoding='utf-8')
    report = build_audit(Path(engine.url.database), tmp_path, range(2026, 2027), check_fts=False)
    assert report['coverage'][0]['status'] == 'official_program_only'
    assert report['paper_count'] == 0
    assert report['full_collection_verified'] is False


def test_audit_detects_secondary_title_index_corruption_without_writing_source(db, engine, sample_paper, tmp_path):
    import sqlite3
    import pytest
    path = Path(engine.url.database)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO paper_titles_fts(paper_titles_fts,rowid,title_norm) VALUES('delete',?,?)",
                           (sample_paper.id, sample_paper.title_norm))
    original = path.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        build_audit(path, tmp_path, range(2024, 2025))
    assert path.read_bytes() == original


def test_official_title_difference_is_not_reported_as_a_missing_identity(db, engine, sample_paper, tmp_path, monkeypatch):
    from types import SimpleNamespace
    import scripts.audit_publications as audit
    sample_paper.publisher_key = 'https://publisher.example.org/paper'
    db.commit()
    raw = SimpleNamespace(title='A different catalogue title', extra={'publisher_key': sample_paper.publisher_key})
    monkeypatch.setattr(audit, 'official_records', lambda *_: [raw])
    (tmp_path / 'official-inventory-001.json').write_text(json.dumps({'units': [
        {'venue': sample_paper.venue.abbr, 'year': 2024, 'inventory_complete': True, 'records': 1}
    ]}), encoding='utf-8')
    report = build_audit(Path(engine.url.database), tmp_path, range(2024, 2025))
    unit = report['coverage'][0]
    assert unit['status'] == 'official_inventory_title_differences'
    assert unit['official_identity_linked'] == 1
    assert unit['official_linked'] == 0
    assert unit['official_missing'] == []
    assert unit['official_title_mismatches'][0]['id'] == sample_paper.id
    assert report['fts_indexes_checked'] == ['papers_fts', 'paper_titles_fts']
    assert not report['full_collection_verified']


def test_final_issue_year_disagreement_is_not_reported_as_missing_identity(db, engine, sample_paper, sample_venue, tmp_path):
    sample_venue.abbr = 'AAAI'
    sample_paper.doi = '10.1609/aaai.v38i1.12345'
    sample_paper.year = 2025
    sample_paper.publisher_key = 'https://publisher.example/final'
    db.commit()
    item = {'DOI': sample_paper.doi, 'title': [sample_paper.title], 'type': 'proceedings-article',
            'published': {'date-parts': [[2024]]},
            'container-title': ['Proceedings of the AAAI Conference on Artificial Intelligence']}
    cache = tmp_path / 'crossref.jsonl'; cache.write_text(json.dumps(item)+'\n', encoding='utf-8')
    (tmp_path/'publisher-repair-001.json').write_text(json.dumps({'prefixes':[
        {'prefix':'10.1609','cache':str(cache),'inventory_complete':True,'records':1}]}), encoding='utf-8')
    report = build_audit(Path(engine.url.database), tmp_path, range(2024,2026), check_fts=False)
    assert report['crossref_identity_missing_count'] == 0
    assert report['crossref_year_mismatch_count'] == 1
    assert report['coverage'][0]['crossref_year_mismatches'][0]['official_inventory']
