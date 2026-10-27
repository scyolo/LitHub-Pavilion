"""Link existing TECS special-issue papers to ESWEEK 2023 conference editions.

ESWEEK 2023 used a journal-integrated publication model: all CODES+ISSS,
CASES and EMSOFT regular papers appeared in ACM TECS 22(5s), while the
conference proceedings only carried companion material. The official
searchable program assigns every paper to exactly one conference session;
this module reuses that per-session membership as evidence and never inserts
new papers or reassigns the canonical journal venue.
"""

import re
from dataclasses import replace
from pathlib import Path

from app.cleaning import normalize_doi
from app.collectors.crossref import item_to_raw
from app.models import Paper
from app.services.paper_conferences import associate_publication
from app.services.paper_store import same_authors

# Special issue identity, verified against Crossref deposits of every article.
TECS_ISSN = "1539-9087"
TECS_TITLE = "ACM Transactions on Embedded Computing Systems"
VOLUME = "22"
ISSUE = "5s"

# Official ESWEEK 2023 program pages; the site lists each conference session
# with its complete paper order. CASES is not a configured CCF source here.
EVIDENCE_URL = "https://2023.esweek.org/events/"
SUPPORTED_CONFERENCES = ("CODES+ISSS", "EMSOFT")

_MAPPING_PATH = (
    Path(__file__).resolve().parents[3] / "release-artifacts/esweek2023-backfill"
)


def session_membership():
    """DOI -> conference abbreviation from the official session program."""
    data = {
        "CODES+ISSS": [],
        "EMSOFT": [],
        "CASES": [],
    }
    import json

    mapping = json.loads(
        (
            _MAPPING_PATH / "tecs-22-5s-conference-mapping.json"
        ).read_text(encoding="utf-8")
    )["doi_to_conference"]
    for doi, conference in mapping.items():
        if conference not in data:
            raise ValueError(f"Unknown ESWEEK 2023 conference in mapping: {conference}")
        data[conference].append(normalize_doi(doi))
    if sum(len(v) for v in data.values()) != 59:
        raise ValueError("Official TECS 22(5s) session mapping is incomplete")
    return data


def issue_paper(item):
    doi = normalize_doi(item.get("DOI")) or ""
    if (
        str(item.get("volume")) != VOLUME
        or item.get("issue") != ISSUE
        or item.get("type") != "journal-article"
        or item.get("container-title") != [TECS_TITLE]
        or TECS_ISSN not in (item.get("ISSN") or [])
        or not re.fullmatch(r"10\.1145/[0-9]+", doi)
    ):
        raise ValueError("Record is outside the verified ESWEEK 2023 TECS issue")
    raw = item_to_raw(item)
    if raw is None or not raw.authors or raw.year != 2023:
        raise ValueError("Missing or conflicting publication metadata")
    return raw


def associate_issue_paper(db, conference, canonical, item, membership, evidence_sha256):
    if (
        conference.abbr not in SUPPORTED_CONFERENCES
        or conference.type != "conf"
        or canonical.abbr != "TECS"
        or canonical.type != "journal"
    ):
        raise ValueError("Configured ESWEEK conference and canonical TECS source required")
    raw = issue_paper(item)
    if raw.doi not in membership.get(conference.abbr, ()):
        raise ValueError("Paper is not in this conference's official sessions")
    paper = db.query(Paper).filter_by(doi=raw.doi).one_or_none()
    if paper is None:
        raise ValueError("Existing canonical publication required; no insertion")
    if not same_authors(db, paper, raw, publisher_verified=True):
        raise ValueError("Complete canonical author list does not match")
    # The shared helper also verifies exact title, canonical venue and public
    # admission. The event year 2023 differs from any journal publication year
    # only in association scope, never on the paper row itself.
    return associate_publication(
        db,
        conference,
        replace(raw, year=2023),
        canonical.id,
        EVIDENCE_URL,
        evidence_sha256,
    )
