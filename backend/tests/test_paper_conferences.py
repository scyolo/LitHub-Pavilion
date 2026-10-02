import pytest

from app.collectors.dblp import RawPaper
from app.models import Paper, Venue
from app.services.paper_conferences import associate_publication


def test_association_reuses_canonical_record_without_reassignment_or_duplication(
    db, sample_paper
):
    conference = Venue(
        abbr="LinkedConf",
        name="Linked Conference",
        type="conf",
        ccf_level="B",
        active=1,
    )
    db.add(conference)
    db.commit()
    raw = RawPaper(
        source="manual",
        venue_key=sample_paper.doi,
        title=sample_paper.title,
        year=2025,
        doi=sample_paper.doi,
        official_url=sample_paper.official_url,
    )
    link, new = associate_publication(
        db,
        conference,
        raw,
        sample_paper.venue_id,
        "https://publisher.example/proceedings/2025",
        "a" * 64,
    )
    assert new is True and link.paper_id == sample_paper.id and link.event_year == 2025
    _, new = associate_publication(
        db,
        conference,
        raw,
        sample_paper.venue_id,
        "https://publisher.example/proceedings/2025",
        "a" * 64,
    )
    assert new is False
    assert db.query(Paper).count() == 1 and sample_paper.year == 2024
    assert sample_paper.venue_id != conference.id


def test_same_doi_wrong_title_cannot_create_conference_evidence(db, sample_paper):
    v = Venue(abbr="Other", name="Other", type="conf", ccf_level="B", active=1)
    db.add(v)
    db.commit()
    raw = RawPaper(
        source="manual",
        venue_key=sample_paper.doi,
        title="Unrelated paper",
        year=2024,
        doi=sample_paper.doi,
    )
    with pytest.raises(ValueError):
        associate_publication(
            db, v, raw, sample_paper.venue_id, "https://publisher.example/toc", "a" * 64
        )


def test_title_only_official_listing_also_requires_matching_authors(db, sample_paper):
    from app.models import Author, PaperAuthor
    from app.services.paper_conferences import associate_title_listing

    event = Venue(abbr="Linked", name="Linked", type="conf", ccf_level="B", active=1)
    author = Author(name="Lee, Ada", name_norm="lee ada")
    db.add_all([event, author])
    db.flush()
    db.add(PaperAuthor(paper_id=sample_paper.id, author_id=author.id, author_order=1))
    db.commit()
    raw = RawPaper(
        source="manual",
        venue_key="title-list",
        title=sample_paper.title,
        authors=["Smith, Bob"],
        year=2024,
    )
    with pytest.raises(ValueError):
        associate_title_listing(
            db,
            event,
            raw,
            sample_paper.venue_id,
            "https://publisher.example/list",
            "a" * 64,
        )
    raw.authors = ["Lee, Ada"]
    link, new = associate_title_listing(
        db,
        event,
        raw,
        sample_paper.venue_id,
        "https://publisher.example/list",
        "a" * 64,
    )
    assert new and link.paper_id == sample_paper.id


def test_initial_only_official_lists_require_exact_title_two_distinct_ordered_authors(
    db, sample_paper
):
    from app.models import Author, PaperAuthor
    from app.services.paper_conferences import associate_title_listing

    conf = Venue(
        abbr="Performance", name="Performance", type="conf", ccf_level="B", active=1
    )
    authors = [
        Author(name="Lee, Alice", name_norm="alice lee"),
        Author(name="Smith, Robert", name_norm="robert smith"),
    ]
    db.add_all([conf, *authors])
    db.flush()
    for i, a in enumerate(authors, 1):
        db.add(PaperAuthor(paper_id=sample_paper.id, author_id=a.id, author_order=i))
    db.commit()
    raw = RawPaper(
        source="manual",
        venue_key="official-list",
        title=sample_paper.title,
        year=2025,
        authors=["Lee, A.", "Smith, R."],
        extra={"provenance": "official_conference_list"},
    )
    with pytest.raises(ValueError):
        associate_title_listing(
            db,
            conf,
            raw,
            sample_paper.venue_id,
            "https://publisher.example/list",
            "b" * 64,
        )
    bad = RawPaper(
        source="manual",
        venue_key="official-list",
        title=sample_paper.title,
        year=2025,
        authors=["Lee, B.", "Smith, R."],
        extra={"provenance": "official_conference_list"},
    )
    with pytest.raises(ValueError):
        associate_title_listing(
            db,
            conf,
            bad,
            sample_paper.venue_id,
            "https://publisher.example/list",
            "b" * 64,
            allow_initial_only=True,
        )
    link, new = associate_title_listing(
        db,
        conf,
        raw,
        sample_paper.venue_id,
        "https://publisher.example/list",
        "b" * 64,
        allow_initial_only=True,
    )
    assert new and link.paper_id == sample_paper.id
