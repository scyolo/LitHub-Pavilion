"""Conservative reader admission; private collection records remain untouched.

The confirmation bit is set by catalogue/container verification, never by a
topic match or a manual venue choice. This gate is necessary but is not a claim
that every external link was probed or every configured CCF grade was re-audited.
"""

import re
from urllib.parse import urlsplit

from sqlalchemy import func

from app.api.serializers import doi_url, safe_http_url
from app.cleaning import is_noise_title, normalize_title
from app.models import Paper, Venue

REPOSITORY_PREFIXES = ("10.48550/", "10.5281/", "10.6084/", "10.31219/", "10.21203/")
REPOSITORY_HOSTS = {
    "arxiv.org",
    "www.arxiv.org",
    "zenodo.org",
    "www.zenodo.org",
    "osf.io",
    "openalex.org",
    "api.openalex.org",
    "semanticscholar.org",
    "www.semanticscholar.org",
}


def nonresearch_title(title):
    normalized = normalize_title(title)
    return (
        not normalized
        or is_noise_title(normalized)
        or normalized in {"preface", "foreword", "acknowledgments", "acknowledgements"}
        or bool(
            re.search(r"[:：]\s*(?:preface|foreword)\s*$", title or "", re.IGNORECASE)
        )
    )


def formal_reference(doi, publisher_key, dblp_key, stream):
    doi_link = doi_url(doi)
    # INFORMS JoC assigns distinct .cd DOIs to code/data repositories, sometimes
    # using the research article title. They are not a second research paper.
    if doi_link and re.fullmatch(
        r"https://doi\.org/10\.1287/ijoc\..+\.cd", doi_link, re.IGNORECASE
    ):
        return None
    if doi_link and not doi_link.removeprefix("https://doi.org/").startswith(
        REPOSITORY_PREFIXES
    ):
        return doi_link
    publisher = safe_http_url(publisher_key)
    if publisher:
        parts = urlsplit(publisher)
        if parts.hostname in {"doi.org", "dx.doi.org"}:
            link = doi_url(publisher)
            if link and not link.removeprefix("https://doi.org/").startswith(
                REPOSITORY_PREFIXES
            ):
                return link
        elif parts.hostname not in REPOSITORY_HOSTS:
            return publisher
    if (
        isinstance(dblp_key, str)
        and isinstance(stream, str)
        and dblp_key.startswith(stream + "/")
        and re.fullmatch(r"(?:conf|journals)/[A-Za-z0-9._/-]+", dblp_key)
        and all(part not in {"", ".", ".."} for part in dblp_key.split("/"))
    ):
        return "https://dblp.org/rec/" + dblp_key
    return None


def admission_reason(paper, venue):
    if (
        venue is None
        or venue.ccf_level not in {"A", "B"}
        or venue.type not in {"conf", "journal"}
        or paper.ccf_level != venue.ccf_level
    ):
        return "source_scope_mismatch"
    if paper.venue_confirmed != 1:
        return "publication_venue_unconfirmed"
    if nonresearch_title(paper.title):
        return "nonresearch_record"
    if not formal_reference(
        paper.doi, paper.publisher_key, paper.dblp_key, venue.dblp_stream
    ):
        return "formal_publication_identity_missing"
    return None


def _eligible_metadata(title, doi, publisher_key, dblp_key, stream):
    return int(
        not nonresearch_title(title)
        and bool(formal_reference(doi, publisher_key, dblp_key, stream))
    )


def reader_admission(db):
    connection = db.connection().connection.driver_connection
    connection.create_function(
        "reader_eligible_metadata", 5, _eligible_metadata, deterministic=True
    )
    return (
        Paper.venue_confirmed == 1,
        Paper.ccf_level == Venue.ccf_level,
        func.reader_eligible_metadata(
            Paper.title,
            Paper.doi,
            Paper.publisher_key,
            Paper.dblp_key,
            Venue.dblp_stream,
        )
        == 1,
    )
