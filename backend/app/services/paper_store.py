"""Upsert metadata in caller-owned transactions; never infer acceptance from a key prefix."""
import re
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.serializers import abstract_text, arxiv_url, safe_http_url
from app.cleaning import author_name_norm, normalize_arxiv_id, normalize_doi, normalize_title
from app.collectors.dblp import RawPaper, stream_prefix
from app.models import Author, Paper, PaperAuthor, Venue
from app.publication import _valid_date
from app.services.publication_identity import preprint_id, publication_authors_match


def _safe_publication_date(value: str | None, year: int) -> str | None:
    """Accept an upstream date only when it is valid and belongs to the unit year."""
    if isinstance(value, str) and _valid_date(value) and value.startswith(f"{year:04d}-"):
        return value
    return None


def is_repository_doi(doi: str | None) -> bool:
    return bool(doi and doi.lower().startswith(("10.48550/", "10.5281/", "10.6084/", "10.31219/", "10.21203/")))


def title_identity_compatible(paper: Paper, raw: RawPaper) -> bool:
    """A title alone cannot collapse two publisher articles or two DBLP keys."""
    if raw.source == "dblp" and paper.dblp_key and paper.dblp_key != raw.venue_key:
        return False
    if raw.source == "openalex" and paper.openalex_id and paper.openalex_id != raw.venue_key:
        return False
    doi = normalize_doi(raw.doi)
    if paper.doi and doi and paper.doi != doi and not (is_repository_doi(paper.doi) or is_repository_doi(doi)):
        return False
    publisher_key = raw.extra.get("publisher_key")
    if publisher_key and paper.publisher_key and publisher_key != paper.publisher_key:
        return False
    aid = normalize_arxiv_id(raw.arxiv_id)
    return not (paper.arxiv_id and aid and paper.arxiv_id != aid)


def same_authors(session, paper, raw, *, publisher_verified=False):
    names = [row[0] for row in session.query(Author.name).join(PaperAuthor)
             .filter(PaperAuthor.paper_id == paper.id).order_by(PaperAuthor.author_order)]
    if publisher_verified:
        shared = bool(preprint_id(paper) and preprint_id(paper) == preprint_id(raw))
        return publication_authors_match(names, raw.authors, shared_identity=shared)
    stored = {author_name_norm(name) for name in names}
    incoming = {author_name_norm(name) for name in raw.authors if author_name_norm(name)}
    return bool(stored) and stored == incoming


def ccf_track_eligible(raw, venue):
    """An official short/Findings paper is not proof of CCF main-track status."""
    identity = " ".join(str(value or "") for value in (
        raw.doi, raw.venue_key, raw.official_url, raw.extra.get("publisher_key")
    )).casefold()
    if venue.abbr == "AAAI":
        # Official issue headings identify non-main tracks. Source issue IDs:
        # https://ojs.aaai.org/index.php/AAAI/issue/view/{560,596,651,729,732}
        excluded = {(37, 13), (38, 21), (39, 28), (40, 47), (40, 48)}
        issue = re.search(r"10\.1609/aaai\.v(\d+)i(\d+)\.", identity)
        if issue and (int(issue[1]), int(issue[2])) in excluded:
            return False
    if venue.abbr == "ACL" and (".acl-short." in identity or ".findings-acl." in identity):
        return False
    if venue.abbr == "EMNLP" and (".findings-emnlp." in identity or ".emnlp-industry." in identity):
        return False
    return True


def upsert_paper(session: Session, raw: RawPaper, venue: Venue, author_cache: dict | None = None) -> tuple[Paper, bool]:
    if venue.ccf_level not in ("A", "B") or venue.type not in ("conf", "journal"):
        raise ValueError("Venue is outside configured A/B scope")
    if not raw.venue_key or not raw.title.strip() or not 2000 <= raw.year <= 2100:
        raise ValueError("Paper identifier, title and publication year are required")
    if raw.source == "dblp" and stream_prefix(raw.venue_key) != venue.dblp_stream:
        raise ValueError("Paper DBLP stream does not match the selected venue")
    doi = normalize_doi(raw.doi)
    arxiv_id = normalize_arxiv_id(raw.arxiv_id) or (normalize_arxiv_id(doi.removeprefix("10.48550/arxiv.")) if doi and doi.startswith("10.48550/arxiv.") else None)
    title_norm = normalize_title(raw.title)

    # Strong identities are resolved first. A title match is deliberately a
    # scoped fallback, never a reason to merge across venues or years.
    publisher_key = safe_http_url(raw.extra.get("publisher_key"))
    if raw.source == "manual" and not (doi or arxiv_id or publisher_key):
        raise ValueError("A DOI, arXiv ID or publisher identity is required")
    strong_filters = []
    if raw.source == "dblp":
        strong_filters.append(Paper.dblp_key == raw.venue_key)
    elif raw.source == "openalex":
        strong_filters.append(Paper.openalex_id == raw.venue_key)
    if publisher_key:
        strong_filters.append(Paper.publisher_key == publisher_key)
    if doi:
        strong_filters.append(Paper.doi == doi)
    if arxiv_id:
        strong_filters.append(Paper.arxiv_id == arxiv_id)
    strong_matches = session.query(Paper).filter(or_(*strong_filters)).all()
    if len(strong_matches) > 1:
        raise ValueError("Identifiers refer to separate existing records; manual review required")
    if strong_matches:
        paper = strong_matches[0]
        if doi and paper.doi and doi != paper.doi and not (is_repository_doi(doi) or is_repository_doi(paper.doi)):
            raise ValueError("Conflicting formal DOIs on a strong identifier")
    else:
        title_matches = (
            session.query(Paper)
            .filter(
                Paper.venue_id == venue.id,
                Paper.year == raw.year,
                Paper.title_norm == title_norm,
            )
            .all()
        )
        title_matches = [] if raw.extra.get("disable_title_match") else [match for match in title_matches if title_identity_compatible(match, raw) and same_authors(session, match, raw)]
        if len(title_matches) > 1:
            raise ValueError("Same title/year maps to separate existing records; manual review required")
        paper = title_matches[0] if title_matches else None
    new = paper is None
    if paper is None:
        paper = Paper(
            source=raw.source, dblp_key=raw.venue_key if raw.source == "dblp" else None,
            openalex_id=raw.venue_key if raw.source == "openalex" else None,
            publisher_key=publisher_key,
            title=raw.title.strip(), title_norm=title_norm, doi=doi, arxiv_id=arxiv_id,
            venue_id=venue.id, year=raw.year, ccf_level=venue.ccf_level, ccf_area=venue.ccf_area,
            official_url=("https://doi.org/" + doi) if doi else safe_http_url(raw.official_url) or "https://dblp.org/db/" + venue.dblp_stream + "/",
            abstract=abstract_text(raw.extra.get("abstract")),
            oa_url=safe_http_url(raw.extra.get("oa_pdf")) or arxiv_url(arxiv_id),
            publication_date=_safe_publication_date(raw.publication_date, raw.year), dblp_mdate=raw.mdate,
            venue_confirmed=int(raw.extra.get("provenance") in ("dblp_toc", "publisher_toc") and ccf_track_eligible(raw, venue)),
            citation_count=max(0, int(raw.extra.get("cited_by_count") or 0)),
            pdf_status="closed",
        )
        session.add(paper)
        session.flush()
    else:
        if paper.venue_id != venue.id:
            raise ValueError("Publication venue conflict; manual review required")
        if raw.source == "dblp" and not paper.dblp_key:
            paper.dblp_key = raw.venue_key
        if raw.source == "openalex" and not paper.openalex_id:
            paper.openalex_id = raw.venue_key
        previous_arxiv_id = normalize_arxiv_id((paper.doi or "").removeprefix("10.48550/arxiv."))
        arxiv_id = arxiv_id or previous_arxiv_id
        if publisher_key and not paper.publisher_key:
            paper.publisher_key = publisher_key
        if doi and (not paper.doi or (is_repository_doi(paper.doi) and not is_repository_doi(doi))):
            paper.doi = doi
            paper.official_url = "https://doi.org/" + doi
        if abstract_text(paper.abstract) is None:
            paper.abstract = abstract_text(raw.extra.get("abstract"))
        if not safe_http_url(paper.oa_url):
            paper.oa_url = safe_http_url(raw.extra.get("oa_pdf")) or arxiv_url(arxiv_id)
        # Only TOC evidence can correct an existing year. Never mix a date
        # from a different source year into a previously confirmed record.
        if raw.extra.get("provenance") in ("dblp_toc", "publisher_toc") and paper.year != raw.year:
            paper.year = raw.year
            paper.publication_date = None
        paper.publication_date = _safe_publication_date(paper.publication_date, paper.year)
        if paper.publication_date is None:
            paper.publication_date = _safe_publication_date(raw.publication_date, paper.year)
        if raw.extra.get("cited_by_count") is not None:
            paper.citation_count = max(0, int(raw.extra["cited_by_count"]))
        if raw.extra.get("provenance") in ("dblp_toc", "publisher_toc"):
            paper.venue_confirmed = int(ccf_track_eligible(raw, venue))
            paper.year = raw.year
        if raw.mdate:
            paper.dblp_mdate = raw.mdate
        if paper.pdf_status in ("pending", "failed"):
            paper.pdf_status = "closed"
    if arxiv_id and not paper.arxiv_id:
        clash = session.query(Paper.id).filter(Paper.arxiv_id == arxiv_id, Paper.id != paper.id).first()
        if not clash:
            paper.arxiv_id = arxiv_id
    corpus_id = raw.extra.get("s2_id")
    if corpus_id and not paper.s2_id and not session.query(Paper.id).filter(Paper.s2_id == corpus_id, Paper.id != paper.id).first():
        paper.s2_id = corpus_id
    if new or not session.query(PaperAuthor).filter(PaperAuthor.paper_id == paper.id).first():
        _add_authors(session, paper.id, raw.authors, author_cache if author_cache is not None else {})
    session.flush()
    return paper, new


def _add_authors(session: Session, paper_id: int, names: list[str], cache: dict) -> None:
    seen = set()
    for name in names:
        norm = author_name_norm(name)
        if not norm:
            continue
        author = cache.get(norm)
        if author is None:
            author = session.query(Author).filter(Author.name_norm == norm).one_or_none()
            if author is None:
                author = Author(name=name, name_norm=norm)
                session.add(author)
                session.flush()
            cache[norm] = author
        if author.id not in seen:
            seen.add(author.id)
            session.add(PaperAuthor(paper_id=paper_id, author_id=author.id, author_order=len(seen)))
