"""Apply independently verified official-list + journal identities in caller-owned transactions."""

from urllib.parse import urlsplit

from app.cleaning import normalize_title
from app.collectors.crossref import item_to_raw
from app.collectors.joint_journal_lists import SPECS
from app.models import Paper, Venue
from app.services.paper_store import ccf_track_eligible, upsert_paper


def store_listed_paper(db, venue, item, source_url, event_year):
    if (
        venue.abbr not in SPECS
        or venue.type != "conf"
        or venue.ccf_level not in ("A", "B")
        or not 2023 <= event_year <= 2026
    ):
        raise ValueError("Unsupported official paper list")
    issn, title = SPECS[venue.abbr]
    host = urlsplit(source_url).hostname
    if urlsplit(source_url).scheme != "https" or host not in (
        {f"{event_year}.sigmod.org"}
        if venue.abbr == "PODS"
        else {"conferences2.sigcomm.org"}
    ):
        raise ValueError("Unexpected evidence source")
    if (
        item.get("ISSN") is None
        or issn not in item["ISSN"]
        or item.get("container-title") != [title]
        or item.get("type") != "journal-article"
    ):
        raise ValueError("Wrong publisher series")
    raw = item_to_raw(item)
    if raw is None or not 2023 <= raw.year <= 2026:
        raise ValueError("Invalid formal paper")
    existing = db.query(Paper).filter_by(doi=raw.doi).one_or_none()
    corrected = False
    if existing:
        if normalize_title(existing.title) != normalize_title(raw.title):
            raise ValueError("Canonical title conflict")
        if existing.venue_id != venue.id:
            old = db.get(Venue, existing.venue_id)
            if (
                venue.abbr != "PODS"
                or old.abbr != "SIGMOD"
                or existing.source != "manual"
                or existing.publisher_key
                or existing.dblp_key
                or existing.openalex_id
                or "Verified publisher metadata: Crossref DOI"
                not in (existing.note or "")
            ):
                raise ValueError(
                    "Existing source is user-curated or lacks the known automatic series assignment"
                )
            previous = f"Corrected automatic PACMMOD-to-SIGMOD assignment to PODS after exact official list verification; prior level {existing.ccf_level}."
            existing.venue_id = venue.id
            existing.ccf_level = venue.ccf_level
            existing.ccf_area = venue.ccf_area
            existing.note = (existing.note + "\n" if existing.note else "") + previous
            db.flush()
            corrected = True
    paper, new = upsert_paper(db, raw, venue)
    paper.venue_confirmed = int(ccf_track_eligible(raw, venue))
    note = f"Exact journal DOI/title/authors matched to official {venue.abbr} {event_year} paper list: {source_url}; publisher year retained"
    if note not in (paper.note or ""):
        paper.note = (paper.note + "\n" if paper.note else "") + note
    return paper, new, corrected
