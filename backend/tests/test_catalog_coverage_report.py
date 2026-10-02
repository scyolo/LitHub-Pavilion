from app.models import Paper, Venue
from scripts.report_catalog_coverage import build_report


def test_report_separates_raw_public_empty_sources_and_does_not_claim_completeness(db, sample_paper):
    empty = Venue(abbr='EMPTY', name='Empty journal', type='journal', ccf_level='B', active=1)
    db.add(empty)
    db.add(Paper(title='Unconfirmed candidate', title_norm='unconfirmed candidate', source='manual',
                 doi='10.1000/candidate', official_url='https://doi.org/10.1000/candidate', venue_id=sample_paper.venue_id, year=2024,
                 ccf_level='A', venue_confirmed=0))
    db.commit()
    report = build_report(db, 2023, 2026)
    assert report['configured_sources'] == 2
    assert report['scoped_database_papers'] == 2
    assert report['public_papers'] == 1
    assert report['nonempty_public_sources'] == 1
    assert report['empty_public_sources'] == ['EMPTY']
    assert report['full_coverage_verified'] is False
    row = next(v for v in report['venues'] if v['abbr'] == 'NeurIPS')
    assert row['years']['2024'] == {'database_papers': 2, 'public_papers': 1}
    assert row['years']['2026']['public_papers'] == 0
    assert db.query(Paper).count() == 2


def test_associations_are_reported_without_double_counting_the_corpus(db,sample_paper):
    from app.models import PaperConference
    extra=Venue(abbr='ConferenceAlias',name='Officially linked event',type='conf',ccf_level='A',active=1)
    db.add(extra);db.flush()
    db.add(PaperConference(paper_id=sample_paper.id,venue_id=extra.id,event_year=2024,evidence_url='https://publisher.example/toc',evidence_sha256='a'*64));db.commit()
    report=build_report(db,2023,2026)
    assert report['public_papers']==1
    assert report['nonempty_public_sources']==1
    assert report['sources_with_direct_or_associated_papers']==2
    row=next(v for v in report['venues'] if v['abbr']=='ConferenceAlias')
    assert row['associated_years']=={'2024':1}
