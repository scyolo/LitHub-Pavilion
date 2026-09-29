from app.collectors.s2 import S2Record
from app.services.enrichment import apply_s2_record, s2_external_id


def test_enrichment_rejects_mismatched_formal_identity_before_updating_text(db, sample_paper):
    sample_paper.abstract = None
    old_count = sample_paper.citation_count
    record = S2Record(title='Unrelated work', abstract='Wrong abstract', doi='10.5555/another',
                      arxiv_id='2401.12345', citation_count=100)
    assert apply_s2_record(db, sample_paper, record) is False
    assert sample_paper.abstract is None and sample_paper.citation_count == old_count
    assert sample_paper.arxiv_id is None


def test_enrichment_matches_title_before_claiming_new_preprint_id(db, sample_paper):
    record = S2Record(title=sample_paper.title, abstract='Accurate abstract', doi=sample_paper.doi,
                      arxiv_id='2401.12345', citation_count=9)
    assert apply_s2_record(db, sample_paper, record) is True
    assert sample_paper.arxiv_id == '2401.12345' and sample_paper.citation_count == 9


def test_enrichment_prefers_formal_identity_over_ambiguous_preprint(db, sample_paper):
    sample_paper.s2_id = '123'
    sample_paper.arxiv_id = '2401.12345'
    assert s2_external_id(sample_paper) == 'DOI:' + sample_paper.doi
