import pytest

from app.cleaning import normalize_title
from app.models import Author, Paper, PaperAuthor, Venue
from app.services.ismb_associations import associate_issue_paper, issue_paper


def record():
    return {
        "DOI": "10.1093/bioinformatics/btag214",
        "title": ["Knowledge-guided contextual gene set analysis with large language models"],
        "container-title": ["Bioinformatics"],
        "ISSN": ["1367-4803"], "type": "journal-article",
        "volume": "42", "issue": "Supplement_1",
        "published-print": {"date-parts": [[2026, 7, 1]]},
        "author": [{"given": "Alice", "family": "Lee"}],
    }


@pytest.mark.parametrize("key,value", [
    ("volume", "41"), ("issue", "Supplement_2"),
    ("container-title", ["Other Journal"]), ("ISSN", ["0000-0000"]),
    ("type", "other"), ("DOI", "10.1093/bioinformatics/btag279"),
    ("DOI", "10.1093/bioinformatics/btag281"), ("author", []),
    ("published-print", {"date-parts": [[2025]]}),
])
def test_only_research_in_the_exact_publisher_issue_is_eligible(key, value):
    item = record()
    item[key] = value
    with pytest.raises(ValueError):
        issue_paper(item, 2026)


def test_association_preserves_canonical_paper_and_is_idempotent(db):
    canonical = Venue(abbr="Bioinformatics", name="Bioinformatics", type="journal",
                      ccf_level="B", active=1)
    conference = Venue(abbr="ISMB", name="ISMB", type="conf", ccf_level="B", active=1)
    author = Author(name="Lee, Alice", name_norm="alice lee")
    db.add_all([canonical, conference, author])
    db.flush()
    item = record()
    with pytest.raises(ValueError, match="no insertion"):
        associate_issue_paper(db, conference, canonical, item, 2026, "a" * 64)
    assert db.query(Paper).count() == 0
    paper = Paper(source="manual", title=item["title"][0],
                  title_norm=normalize_title(item["title"][0]), doi=item["DOI"],
                  official_url="https://doi.org/" + item["DOI"],
                  year=2025, venue_id=canonical.id, venue_confirmed=1,
                  ccf_level="B", abstract="Existing meaningful abstract", note="My note")
    db.add(paper)
    db.flush()
    db.add(PaperAuthor(paper_id=paper.id, author_id=author.id, author_order=1))
    db.flush()
    link, new = associate_issue_paper(db, conference, canonical, item, 2026, "a" * 64)
    assert new and link.paper_id == paper.id and link.event_year == 2026
    assert not associate_issue_paper(db, conference, canonical, item, 2026, "a" * 64)[1]
    assert (paper.year, paper.venue_id, paper.note, paper.abstract) == (
        2025, canonical.id, "My note", "Existing meaningful abstract")
    assert db.query(Paper).count() == 1
    item["author"] = [{"given": "Bob", "family": "Smith"}]
    with pytest.raises(ValueError, match="author"):
        associate_issue_paper(db, conference, canonical, item, 2026, "a" * 64)
    item["author"] = record()["author"]
    item["title"] = ["Unrelated publication"]
    with pytest.raises(ValueError, match="title"):
        associate_issue_paper(db, conference, canonical, item, 2026, "a" * 64)
