import pytest

from app.models import Paper, Venue
from app.services.listed_journal_papers import store_listed_paper


def metadata():
    return {
        "DOI": "10.1145/1234567",
        "type": "journal-article",
        "title": ["Query optimization"],
        "author": [{"given": "Ada", "family": "Lee"}],
        "container-title": ["Proceedings of the ACM on Management of Data"],
        "ISSN": ["2836-6573"],
        "published": {"date-parts": [[2024]]},
    }


def test_official_pods_list_corrects_only_auto_sigmod_assignment_without_duplicate(db):
    sigmod = Venue(abbr="SIGMOD", name="SIGMOD", type="conf", ccf_level="A", active=1)
    pods = Venue(abbr="PODS", name="PODS", type="conf", ccf_level="B", active=1)
    db.add_all([sigmod, pods])
    db.flush()
    p = Paper(
        source="manual",
        title="Query optimization",
        title_norm="query optimization",
        year=2024,
        venue_id=sigmod.id,
        ccf_level="A",
        venue_confirmed=1,
        doi="10.1145/1234567",
        official_url="https://doi.org/10.1145/1234567",
        note="Verified publisher metadata: Crossref DOI 10.1145/1234567",
    )
    db.add(p)
    db.commit()
    pid = p.id
    result, new, corrected = store_listed_paper(
        db, pods, metadata(), "https://2024.sigmod.org/pods_list.shtml", 2024
    )
    db.commit()
    assert not new and corrected and result.id == pid
    assert (
        result.venue_id == pods.id
        and result.ccf_level == "B"
        and db.query(Paper).count() == 1
    )


def test_user_curated_or_other_source_identity_is_not_reassigned(db):
    source = Venue(abbr="SIGMOD", name="SIGMOD", type="conf", ccf_level="A", active=1)
    target = Venue(abbr="PODS", name="PODS", type="conf", ccf_level="B", active=1)
    db.add_all([source, target])
    db.flush()
    p = Paper(
        source="manual",
        title="Query optimization",
        title_norm="query optimization",
        year=2024,
        venue_id=source.id,
        ccf_level="A",
        venue_confirmed=1,
        doi="10.1145/1234567",
        official_url="https://doi.org/10.1145/1234567",
        note="User entered paper",
    )
    db.add(p)
    db.commit()
    with pytest.raises(ValueError):
        store_listed_paper(
            db, target, metadata(), "https://2024.sigmod.org/pods_list.shtml", 2024
        )
    assert p.venue_id == source.id
