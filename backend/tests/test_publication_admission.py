from types import SimpleNamespace

import pytest

from app.api.filtering import PaperFilters, paper_query
from app.models import Paper
from app.services.publication_admission import admission_reason, formal_reference


def test_unconfirmed_records_are_not_reader_papers_but_remain_private(db, sample_paper):
    sample_paper.venue_confirmed = 0
    db.commit()
    assert paper_query(db, PaperFilters()).count() == 0
    assert paper_query(db, PaperFilters(), include_candidates=True).count() == 1
    assert db.get(Paper, sample_paper.id) is sample_paper


def test_candidates_cannot_bypass_reader_gate_via_search_stats_detail_or_export(
    client, db, sample_paper, session_factory, tmp_path
):
    from app.services.snapshot import export_snapshot

    sample_paper.venue_confirmed = 0
    db.commit()
    assert client.get("/api/papers").json()["total"] == 0
    assert (
        client.get("/api/search", params={"q": sample_paper.title}).json()["total"] == 0
    )
    assert client.get("/api/stats/dashboard").json()["total"] == 0
    assert client.get(f"/api/papers/{sample_paper.id}").status_code == 404
    with pytest.raises(ValueError, match="empty"):
        export_snapshot(session_factory, tmp_path)
    assert db.query(Paper).count() == 1


def test_cross_direction_tags_do_not_override_publication_evidence(
    db, sample_paper, sample_direction
):
    from app.models import PaperDirection

    db.add(
        PaperDirection(
            paper_id=sample_paper.id,
            direction_id=sample_direction.id,
            score=99,
            source="manual",
        )
    )
    sample_paper.venue_confirmed = 0
    db.commit()
    assert (
        paper_query(db, PaperFilters(directions=(sample_direction.code,))).count() == 0
    )
    assert db.query(PaperDirection).count() == 1


@pytest.mark.parametrize(
    "title",
    [
        "Conference on Learning Theory 2025: Preface",
        "Editorial Board",
        "Preface",
        "Front Matter",
    ],
)
def test_nonresearch_publication_records_do_not_enter_reader_stats(
    db, sample_paper, title
):
    sample_paper.title = title
    db.commit()
    assert paper_query(db, PaperFilters()).count() == 0
    assert db.query(Paper).count() == 1


@pytest.mark.parametrize(
    "doi",
    ["10.48550/arxiv.2501.12345", "10.5281/zenodo.123456", "10.6084/m9.figshare.1234"],
)
def test_repository_doi_does_not_establish_formal_venue_membership(doi):
    assert formal_reference(doi, "https://doi.org/" + doi, None, "conf/nips") is None


def test_official_doi_optional_article_can_be_admitted(db, sample_paper):
    sample_paper.doi = None
    sample_paper.source = "manual"
    sample_paper.dblp_key = None
    sample_paper.publisher_key = "https://papers.nips.cc/paper_files/paper/2024/hash/verified-Abstract-Conference.html"
    db.commit()
    assert paper_query(db, PaperFilters()).count() == 1
    assert admission_reason(sample_paper, sample_paper.venue) is None


def test_missing_or_wrong_source_and_preprints_are_rejected():
    venue = SimpleNamespace(ccf_level="A", type="conf", dblp_stream="conf/nips")
    paper = SimpleNamespace(
        ccf_level="A",
        venue_confirmed=1,
        title="Learning",
        doi=None,
        publisher_key="https://arxiv.org/abs/2501.12345",
        dblp_key="conf/icml/wrong",
    )
    assert admission_reason(paper, venue) == "formal_publication_identity_missing"
    assert admission_reason(paper, None) == "source_scope_mismatch"
    paper.ccf_level = "B"
    assert admission_reason(paper, venue) == "source_scope_mismatch"


@pytest.mark.parametrize(
    "title",
    [
        "Code and Data Repository for Queueing Algorithms",
        "An Approximation Algorithm for Vehicle Routing",
    ],
)
def test_informs_code_repository_doi_is_not_a_second_research_paper(
    db, sample_paper, title
):
    sample_paper.doi = "10.1287/ijoc.2021.0193.cd"
    sample_paper.title = title
    sample_paper.publisher_key = (
        "https://pubsonline.informs.org/doi/10.1287/ijoc.2021.0193.cd"
    )
    db.commit()
    assert paper_query(db, PaperFilters()).count() == 0
    assert db.query(Paper).count() == 1
    assert (
        formal_reference("10.1287/ijoc.2021.0193", None, None, None)
        == "https://doi.org/10.1287/ijoc.2021.0193"
    )
