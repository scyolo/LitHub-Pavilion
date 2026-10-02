"""Attach explicit official-list evidence without duplicating/reassigning journal papers."""

import re

from app.api.serializers import safe_http_url
from app.cleaning import normalize_doi, normalize_title
from app.models import Paper, PaperConference, Venue
from app.services.paper_store import upsert_paper
from app.services.publication_admission import admission_reason


def associate_publication(
    session, conference, raw, canonical_venue_id, evidence_url, evidence_sha256
):
    if (
        conference.type != "conf"
        or conference.ccf_level not in ("A", "B")
        or not 2023 <= raw.year <= 2026
    ):
        raise ValueError("Invalid conference association scope")
    if not safe_http_url(evidence_url) or not re.fullmatch(
        r"[0-9a-f]{64}", evidence_sha256
    ):
        raise ValueError("Verified source URL and evidence hash required")
    doi = normalize_doi(raw.doi)
    if not doi:
        raise ValueError("Exact DOI required for cross-source association")
    canonical = session.get(Venue, canonical_venue_id)
    if canonical is None or canonical.ccf_level not in ("A", "B"):
        raise ValueError("Missing canonical A/B source")
    paper = session.query(Paper).filter_by(doi=doi).one_or_none()
    if paper:
        if paper.venue_id != canonical.id or normalize_title(
            paper.title
        ) != normalize_title(raw.title):
            raise ValueError("Canonical DOI/title/source conflict")
    else:
        if raw.extra.get("provenance") != "publisher_toc":
            raise ValueError("Official publisher metadata needed for a new paper")
        paper, _ = upsert_paper(session, raw, canonical)
    if admission_reason(paper, canonical) is not None:
        raise ValueError("Canonical paper is not public-admitted")
    key = (paper.id, conference.id, raw.year)
    link = session.get(PaperConference, key)
    if link:
        return link, False
    link = PaperConference(
        paper_id=paper.id,
        venue_id=conference.id,
        event_year=raw.year,
        evidence_url=evidence_url,
        evidence_sha256=evidence_sha256,
    )
    session.add(link)
    session.flush()
    return link, True


def associate_title_listing(
    session,
    conference,
    raw,
    canonical_venue_id,
    evidence_url,
    evidence_sha256,
    *,
    allow_initial_only=False,
):
    from dataclasses import replace

    from app.services.paper_store import same_authors

    matches = (
        session.query(Paper)
        .filter_by(venue_id=canonical_venue_id, title_norm=normalize_title(raw.title))
        .all()
    )

    def verified_initials(paper):
        from app.models import Author, PaperAuthor
        from app.services.publication_identity import _name_match, _parts

        if (
            not allow_initial_only
            or raw.extra.get("provenance") != "official_conference_list"
        ):
            return False
        names = [
            name
            for (name,) in session.query(Author.name)
            .join(PaperAuthor)
            .filter(PaperAuthor.paper_id == paper.id)
            .order_by(PaperAuthor.author_order)
        ]
        if len(names) != len(raw.authors) or len(names) < 2:
            return False
        families = [_parts(name)[0] for name in names]
        if len(set(families)) != len(families):
            return False
        # Only a complete, ordered list with distinct surnames may use initials.
        # This exception associates an existing exact-title record, never merges it.
        return all(
            _name_match(first, second)[0] for first, second in zip(names, raw.authors)
        )

    matches = [
        p
        for p in matches
        if p.doi
        and (
            same_authors(session, p, raw, publisher_verified=True)
            or verified_initials(p)
        )
    ]
    if len(matches) != 1:
        raise ValueError("Official title/author list has no unique canonical match")
    paper = matches[0]
    return associate_publication(
        session,
        conference,
        replace(raw, doi=paper.doi),
        canonical_venue_id,
        evidence_url,
        evidence_sha256,
    )
