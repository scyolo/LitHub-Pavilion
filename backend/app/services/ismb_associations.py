"""Link existing Bioinformatics papers to explicitly identified ISMB issues."""

import re
from dataclasses import replace

from app.cleaning import normalize_doi, normalize_title
from app.collectors.crossref import item_to_raw
from app.models import Paper
from app.services.paper_conferences import associate_publication
from app.services.paper_store import same_authors

# Publisher editorials identify these exact supplements as the proceedings.
# The first excluded DOI is the editorial; the remainder are award profiles.
ISSUES = {
    2023: {
        "volume": "39",
        "editorial": "https://academic.oup.com/bioinformatics/article/39/Supplement_1/i1/7210454",
        "excluded": ("btad319", "btad316", "btad318", "btad307", "btad306"),
    },
    2025: {
        "volume": "41",
        "editorial": "https://academic.oup.com/bioinformatics/article/41/Supplement_1/i1/8199417",
        "excluded": ("btaf271", "btaf263", "btaf262", "btaf260", "btaf261"),
    },
    2026: {
        "volume": "42",
        "editorial": "https://academic.oup.com/bioinformatics/article/42/Supplement_1/btag279/8726347",
        "excluded": ("btag279", "btag280", "btag282", "btag281", "btag283"),
    },
}


def issue_paper(item, event_year):
    issue = ISSUES.get(event_year)
    doi = normalize_doi(item.get("DOI")) or ""
    if (
        not issue
        or str(item.get("volume")) != issue["volume"]
        or item.get("issue") != "Supplement_1"
        or item.get("type") != "journal-article"
        or item.get("container-title") != ["Bioinformatics"]
        or "1367-4803" not in (item.get("ISSN") or [])
        or not re.fullmatch(r"10\.1093/bioinformatics/[a-z]+[0-9]+", doi)
    ):
        raise ValueError("Record is outside the verified ISMB issue")
    if doi.rsplit("/", 1)[-1] in issue["excluded"]:
        raise ValueError("Editorial or award profile is not a research paper")
    raw = item_to_raw(item)
    if raw is None or not raw.authors or raw.year != event_year:
        raise ValueError("Missing or conflicting publication metadata")
    return raw


def associate_issue_paper(db, conference, canonical, item, event_year, evidence_sha256):
    if (
        conference.abbr != "ISMB"
        or canonical.type != "journal"
        or normalize_title(canonical.name) != "bioinformatics"
    ):
        raise ValueError("ISMB and canonical Bioinformatics sources required")
    raw = issue_paper(item, event_year)
    paper = db.query(Paper).filter_by(doi=raw.doi).one_or_none()
    if paper is None:
        raise ValueError("Existing canonical publication required; no insertion")
    if not same_authors(db, paper, raw, publisher_verified=True):
        raise ValueError("Complete canonical author list does not match")
    # The association helper also verifies exact title, canonical venue and
    # public admission. It must never receive a missing canonical publication.
    return associate_publication(
        db,
        conference,
        replace(raw, year=event_year),
        canonical.id,
        ISSUES[event_year]["editorial"],
        evidence_sha256,
    )
