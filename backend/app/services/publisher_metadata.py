"""Apply DOI/container-verified publisher metadata without conflating versions."""
from collections import Counter
from dataclasses import replace
from difflib import SequenceMatcher
from app.cleaning import is_noise_title, normalize_title
from app.collectors.crossref import identify_venue, item_to_raw, metadata_text
from app.models import Paper, Venue
from app.services.paper_store import _safe_publication_date, ccf_track_eligible, same_authors, upsert_paper


def apply_items(session, items, years, *, commit=True):
    venues = {v.abbr: v for v in session.query(Venue).filter(Venue.active == 1, Venue.ccf_level.in_(("A", "B"))).all()}
    stats = Counter()
    conflicts = []
    changed = []
    for item in items:
        venue = identify_venue(item, venues)
        raw = item_to_raw(item) if venue else None
        if raw and venue.type == "conf":
            from app.collectors.catalog_conferences import conference_year
            event_year = conference_year(item, venue)
            if event_year is not None:
                raw = replace(raw, year=event_year, publication_date=raw.publication_date if (raw.publication_date or "").startswith(str(event_year)) else None)
        if not raw or raw.year not in years or is_noise_title(normalize_title(raw.title)):
            stats["out_of_scope"] += 1
            continue
        existing = session.query(Paper).filter(Paper.doi == raw.doi).one_or_none()
        title_changed = existing and existing.title_norm != normalize_title(raw.title)
        # A DOI plus matching container and exactly the same text modulo
        # markup/spacing permits a typography-only correction, even when author
        # names are abbreviated. Semantic title changes still need equal author
        # sets and high similarity; this never permits cross-venue merging.
        typography_only = existing and (
            normalize_title(metadata_text(existing.title)).replace(" ", "") ==
            normalize_title(raw.title).replace(" ", ""))
        title_verified = (not title_changed or typography_only or
            (same_authors(session, existing, raw, publisher_verified=True) and
             SequenceMatcher(None, existing.title_norm, normalize_title(raw.title)).ratio() >= 0.8))
        if existing and (existing.venue_id != venue.id or not title_verified):
            conflicts.append({"id": existing.id, "doi": raw.doi, "stored_title": existing.title,
                              "publisher_title": raw.title, "publisher_year": raw.year, "venue": venue.abbr})
            stats["identity_conflicts"] += 1
            continue
        # Publisher issue/volume records are the authoritative final title/year.
        # Crossref can retain early-access years indefinitely (even in its
        # published-print field); a scheduled fallback must never regress them.
        preserved_note = None
        if existing and existing.publisher_key:
            if title_changed or existing.year != raw.year:
                preserved_note = (f"Publisher inventory retained over Crossref metadata: DOI {raw.doi}; "
                                  f"Crossref year {raw.year}; Crossref title: {raw.title}")
                stats["official_metadata_preserved"] += 1
            raw = replace(raw, title=existing.title, year=existing.year,
                          publication_date=existing.publication_date)
            title_changed = False
        try:
            with session.begin_nested():
                paper, new = upsert_paper(session, raw, venue)
                old_year = paper.year
                if title_changed:
                    paper.note = ((paper.note + "\n") if paper.note else "") + "Previous indexed title: " + paper.title
                    paper.title, paper.title_norm = raw.title, normalize_title(raw.title)
                    stats["titles_corrected"] += 1
                if paper.year != raw.year:
                    paper.year = raw.year
                    paper.publication_date = None
                    stats["years_corrected"] += 1
                # Evidence is the exact DOI and the publisher's matched container,
                # not an arXiv upload date, key suffix or guessed year.
                paper.publication_date = _safe_publication_date(paper.publication_date, paper.year) or raw.publication_date
                paper.venue_confirmed = int(ccf_track_eligible(raw, venue))
                provenance = "Verified publisher metadata: Crossref DOI " + raw.doi
                if item.get("_ecml_parent"):
                    provenance += "; conference year verified from parent " + item["_ecml_parent"]["DOI"]
                if item.get("type") == "journal-article" and venue.type == "conf":
                    provenance += "; explicit journal research-track issue " + str(item.get("issue")) + "; year is journal publication/volume year, presentation year not inferred"
                if item.get("_catalog_book_parent"):
                    provenance += "; event edition verified from parent book " + item["_catalog_book_parent"]["DOI"]
                if preserved_note and preserved_note not in (paper.note or ""):
                    paper.note = ((paper.note + "\n") if paper.note else "") + preserved_note
                if provenance not in (paper.note or ""):
                    paper.note = ((paper.note + "\n") if paper.note else "") + provenance
                stats["new" if new else "updated"] += 1
                stats[f"venue:{venue.abbr}/{raw.year}"] += 1
                if new or old_year != raw.year:
                    changed.append({"id": paper.id, "doi": raw.doi, "venue": venue.abbr,
                                    "old_year": None if new else old_year, "year": raw.year, "new": new})
        except ValueError as exc:
            stats["identity_conflicts"] += 1
            conflicts.append({"doi": raw.doi, "publisher_title": raw.title, "reason": str(exc)})
    if commit:
        session.commit()
    return {"counts": dict(stats), "changes": changed, "conflicts": conflicts}
