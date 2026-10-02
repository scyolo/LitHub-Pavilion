"""Conservative publication matching shared by scheduled and repair imports."""
from collections import Counter
from dataclasses import replace
from difflib import SequenceMatcher
from sqlalchemy import or_
from app.api.serializers import safe_http_url
from app.cleaning import normalize_title, author_name_norm
from app.models import Paper
from app.services.paper_store import ccf_track_eligible, is_repository_doi, same_authors, title_identity_compatible, upsert_paper


def compatible_title(paper, raw):
    old, new = paper.title_norm, normalize_title(raw.title)
    return (old == new or SequenceMatcher(None, old, new).ratio() >= 0.85
            or (min(len(old), len(new)) >= 60 and (old.startswith(new + ' ') or new.startswith(old + ' '))))


def fill_missing_oa_links(session, records, venue):
    """Repair only blank OA fields on independently verified existing identities.

    Never insert publications, replace nonempty links, or modify paper metadata
    and manual labels. Publisher parsers must supply the link, not guess it.
    """
    stats = Counter()
    changes, conflicts = [], []
    for raw in records:
        key = safe_http_url(raw.extra.get("publisher_key"))
        link = safe_http_url(raw.extra.get("oa_pdf"))
        if not key or not link:
            stats["no_verified_oa"] += 1
            continue
        paper = session.query(Paper).filter(Paper.publisher_key == key).one_or_none()
        if paper is None:
            stats["missing_publication"] += 1
            continue
        if (paper.venue_id != venue.id or paper.year != raw.year
                or not compatible_title(paper, raw)
                or not same_authors(session, paper, raw, publisher_verified=True)):
            stats["identity_conflicts"] += 1
            conflicts.append({"url": key, "reason": "Existing publication metadata does not verify the OA link"})
            continue
        if paper.oa_url and paper.oa_url.strip():
            stats["already_linked"] += 1
            continue
        paper.oa_url = link
        stats["updated"] += 1
        changes.append({"id": paper.id, "oa_url": link})
    session.commit()
    return {"counts": dict(stats), "changes": changes, "conflicts": conflicts, "associations": []}


def apply_records(session, records, venue):
    stats = Counter(); changes = []; conflicts = []; associations = []
    for original in records:
        raw = replace(original, extra=dict(original.extra))
        author_keys = [author_name_norm(name) for name in raw.authors]
        if len(author_keys) != len(set(author_keys)):
            # The current Author/PaperAuthor schema is name-keyed. Until it
            # supports distinct author slots, never confirm a lossy import.
            stats['identity_conflicts'] += 1
            conflicts.append({'url': raw.official_url, 'doi': raw.doi,
                              'reason': 'author_multiplicity_not_representable',
                              'authors': list(raw.authors)})
            continue
        key = safe_http_url(raw.extra.get('publisher_key'))
        if not key:
            stats['identity_conflicts'] += 1
            conflicts.append({'url': raw.official_url, 'reason': 'Missing or unsafe official publication identity'})
            continue
        raw.extra['publisher_key'] = key
        raw.official_url = safe_http_url(raw.official_url) or key
        association_notes = []
        if raw.extra.get('publisher_title_correction'):
            association_notes.append('Verified publisher title correction: ' + raw.extra['publisher_title_correction'] + '; catalogue title: ' + raw.extra['catalogue_title'])
        # One preprint can legitimately underlie a conference paper AND its
        # journal extension. Keep distinct publication identities and preserve
        # the catalogue's OA link rather than dropping the other publication
        # because the legacy arxiv_id column is globally unique.
        if raw.arxiv_id:
            owner = session.query(Paper).filter(Paper.arxiv_id == raw.arxiv_id).one_or_none()
            if owner and (owner.venue_id != venue.id
                    or not compatible_title(owner, raw)
                    or (owner.publisher_key and owner.publisher_key != raw.extra['publisher_key'])
                    or (owner.doi and raw.doi and owner.doi != raw.doi and not is_repository_doi(owner.doi))):
                link = 'https://arxiv.org/abs/' + raw.arxiv_id
                raw.extra['oa_pdf'] = link  # link only; never downloaded
                association_notes.append(f'Official catalogue preprint link: {link}; also associated with paper {owner.id}; publications kept separate')
                associations.append({'url': raw.official_url, 'arxiv_id': raw.arxiv_id, 'other_id': owner.id, 'reason': 'shared preprint link; separate official publication'})
                stats['shared_preprint_links'] += 1
                raw.arxiv_id = None
        # A publisher page may itself contain a wrong/repeated DOI. Its unique
        # official article URL still proves the paper exists. Do not attach the
        # conflicting DOI or overwrite the first publication's metadata.
        if raw.doi:
            owner = session.query(Paper).filter(Paper.doi == raw.doi).one_or_none()
            if owner and (owner.venue_id != venue.id or not compatible_title(owner, raw)):
                association_notes.append(f'Unresolved DOI reported by official catalogue: {raw.doi}; conflicts with paper {owner.id}; DOI not assigned to this publication')
                associations.append({'url': raw.official_url, 'doi': raw.doi, 'other_id': owner.id, 'reason': 'DOI/title or venue conflict; retained by official URL only'})
                stats['association_conflicts'] += 1
                raw.doi = None
        strong = [Paper.publisher_key == raw.extra['publisher_key']]
        if raw.doi:
            strong.append(Paper.doi == raw.doi)
        if raw.arxiv_id:
            strong.append(Paper.arxiv_id == raw.arxiv_id)
        hits = session.query(Paper).filter(or_(*strong)).all()
        if len(hits) > 1:
            stats['identity_conflicts'] += 1
            conflicts.append({'url': raw.official_url, 'ids': [p.id for p in hits], 'reason': 'split strong identities'})
            continue
        if hits:
            selected = hits[0]
            if selected.venue_id != venue.id or not compatible_title(selected, raw):
                stats['identity_conflicts'] += 1
                conflicts.append({'url': raw.official_url, 'id': selected.id, 'reason': 'strong ID title/venue mismatch'})
                continue
        else:
            candidates = session.query(Paper).filter(Paper.venue_id == venue.id, Paper.title_norm == normalize_title(raw.title)).all()
            verified = [p for p in candidates if title_identity_compatible(p, raw) and same_authors(session, p, raw, publisher_verified=True) and (
                p.year == raw.year or (not p.publisher_key and (not p.doi or is_repository_doi(p.doi))))]
            selected = verified[0] if len(verified) == 1 else None
            if len(verified) > 1:
                stats['identity_conflicts'] += 1
                conflicts.append({'url': raw.official_url, 'ids': [p.id for p in verified], 'reason': 'multiple verified title+author candidates'})
                continue
        old_year = selected.year if selected else None
        try:
            with session.begin_nested():
                # Attach a real publisher key only after the verification above.
                if selected:
                    selected.publisher_key = raw.extra['publisher_key']
                    session.flush()
                raw.extra['disable_title_match'] = True
                paper, new = upsert_paper(session, raw, venue)
                if paper.title != raw.title:
                    paper.note = ((paper.note + '\n') if paper.note else '') + 'Previous indexed title: ' + paper.title
                    paper.title, paper.title_norm = raw.title, normalize_title(raw.title)
                    stats['titles_corrected'] += 1
                evidence = 'Verified official proceedings: ' + raw.official_url
                if evidence not in (paper.note or ''):
                    paper.note = ((paper.note + '\n') if paper.note else '') + evidence
                for note in association_notes:
                    if note not in (paper.note or ''):
                        paper.note = ((paper.note + '\n') if paper.note else '') + note
                paper.venue_confirmed = int(ccf_track_eligible(raw, venue))
                stats['new' if new else 'updated'] += 1
                if old_year is not None and old_year != paper.year:
                    stats['years_corrected'] += 1
                if new or old_year != paper.year:
                    changes.append({'id': paper.id, 'new': new, 'old_year': old_year, 'year': paper.year})
        except ValueError as exc:
            stats['identity_conflicts'] += 1
            conflicts.append({'url': raw.official_url, 'reason': str(exc)})
    session.commit()
    return {'counts': dict(stats), 'changes': changes, 'conflicts': conflicts, 'associations': associations}
