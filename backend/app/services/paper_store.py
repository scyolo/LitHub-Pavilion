"""Upsert metadata in caller-owned transactions; never infer acceptance from a key prefix."""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.serializers import abstract_text, arxiv_url, safe_http_url
from app.cleaning import author_name_norm, normalize_arxiv_id, normalize_doi, normalize_title
from app.collectors.dblp import RawPaper, stream_prefix
from app.config import settings
from app.models import Author, Paper, PaperAuthor, Venue


def upsert_paper(session: Session, raw: RawPaper, venue: Venue, author_cache: dict | None = None) -> tuple[Paper, bool]:
    if venue.ccf_level not in ("A", "B") or venue.type not in ("conf", "journal"):
        raise ValueError("Venue is outside configured A/B scope")
    if not raw.venue_key or not raw.title.strip() or not 2000 <= raw.year <= 2100:
        raise ValueError("Paper identifier, title and publication year are required")
    if raw.source == "dblp" and stream_prefix(raw.venue_key) != venue.dblp_stream:
        raise ValueError("Paper DBLP stream does not match the selected venue")
    doi = normalize_doi(raw.doi)
    arxiv_id = normalize_arxiv_id(raw.arxiv_id)
    identifier_column = Paper.dblp_key if raw.source == "dblp" else Paper.openalex_id
    candidates = [identifier_column == raw.venue_key]
    if doi:
        candidates.append(Paper.doi == doi)
    matches = session.query(Paper).filter(or_(*candidates)).all()
    if len(matches) > 1:
        raise ValueError("Identifiers refer to separate existing records; manual review required")
    paper = matches[0] if matches else None
    new = paper is None
    if paper is None:
        paper = Paper(
            source=raw.source, dblp_key=raw.venue_key if raw.source == "dblp" else None,
            openalex_id=raw.venue_key if raw.source == "openalex" else None,
            title=raw.title.strip(), title_norm=normalize_title(raw.title), doi=doi,
            venue_id=venue.id, year=raw.year, ccf_level=venue.ccf_level, ccf_area=venue.ccf_area,
            official_url=("https://doi.org/" + doi) if doi else safe_http_url(raw.official_url) or "https://dblp.org/db/" + venue.dblp_stream + "/",
            abstract=abstract_text(raw.extra.get("abstract")),
            oa_url=safe_http_url(raw.extra.get("oa_pdf")) or arxiv_url(arxiv_id),
            publication_date=raw.publication_date, dblp_mdate=raw.mdate,
            venue_confirmed=int(raw.extra.get("provenance") == "dblp_toc"),
            citation_count=max(0, int(raw.extra.get("cited_by_count") or 0)),
            pdf_status="pending" if settings.pdf_download_enabled else "closed",
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
        if not paper.doi:
            paper.doi = doi
        if abstract_text(paper.abstract) is None:
            paper.abstract = abstract_text(raw.extra.get("abstract"))
        if not safe_http_url(paper.oa_url):
            paper.oa_url = safe_http_url(raw.extra.get("oa_pdf")) or arxiv_url(arxiv_id)
        if paper.publication_date is None:
            paper.publication_date = raw.publication_date
        if raw.extra.get("cited_by_count") is not None:
            paper.citation_count = max(0, int(raw.extra["cited_by_count"]))
        if raw.extra.get("provenance") == "dblp_toc":
            paper.venue_confirmed = 1
            paper.year = raw.year
        if raw.mdate:
            paper.dblp_mdate = raw.mdate
        if not settings.pdf_download_enabled and paper.pdf_status in ("pending", "failed"):
            paper.pdf_status = "closed"
    if arxiv_id and not paper.arxiv_id:
        clash = session.query(Paper.id).filter(Paper.arxiv_id == arxiv_id, Paper.id != paper.id).first()
        if not clash:
            paper.arxiv_id = arxiv_id
    if new:
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
