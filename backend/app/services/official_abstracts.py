"""Fill missing abstracts from a previously verified official HTML inventory.

Does not admit papers, change formal metadata, overwrite text, or fetch URLs.
The caller must retain source evidence and commit the transaction explicitly.
"""
from collections import Counter

from app.cleaning import normalize_doi, normalize_title, author_name_norm, clean_author_name
from app.models import Author, Paper, PaperAuthor
from app.services.publication_identity import _tokens


def fill_verified_abstracts(session, rows, venue_id, year):
    filled, rejected = [], []
    seen = set()
    for row in rows:
        doi = normalize_doi(row.get('doi'))
        if not doi or doi in seen:
            raise ValueError('Missing or duplicate official abstract DOI')
        seen.add(doi)
        paper = session.query(Paper).filter(Paper.doi == doi, Paper.venue_id == venue_id,
                                           Paper.year == year, Paper.venue_confirmed == 1).one_or_none()
        if paper is None or (paper.abstract or '').strip():
            continue
        names = [name for name, in session.query(Author.name).join(PaperAuthor).filter(PaperAuthor.paper_id == paper.id)]
        source = row.get('authors') or []
        abstract = row.get('abstract')
        if (paper.title_norm != normalize_title(row.get('title') or '')
                or not names or not source
                or any(not _tokens(name) for name in source)
                or (Counter(tuple(sorted(_tokens(name))) for name in names) != Counter(tuple(sorted(_tokens(name))) for name in source)
                    and Counter(author_name_norm(clean_author_name(name)) for name in names) != Counter(author_name_norm(clean_author_name(name)) for name in source))
                or not isinstance(abstract, str) or not abstract.strip() or len(abstract) > 100000):
            rejected.append({'id': paper.id, 'doi': doi, 'reason': 'title_authors_or_abstract_invalid'})
            continue
        paper.abstract = abstract.strip()
        filled.append(paper.id)
    session.flush()
    return {'filled': filled, 'rejected': rejected}
