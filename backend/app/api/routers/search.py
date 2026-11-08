"""FTS5 英文全文检索：参数绑定、有限词数、共享 scope 和稳定排序。"""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Float, Integer, bindparam, func, literal, select, text, union
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.filtering import PAPER_SORTS, PaperFilters, bad_request, paper_filters, paper_query
from app.api.serializers import authors_for, directions_for, paper_card
from app.models import Author, Direction, Paper, PaperAuthor, PaperDirection
from app.cleaning import normalize_title
from app.services.fuzzy_terms import expand_tokens, title_vocabulary
from app.services.search_tokens import stemmer
from app.services.query_aliases import keyword_query, query_topic

router = APIRouter(prefix="/api/search", tags=["search"])

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]")


MAX_TITLE_QUERY = 2000


def _build_match_expr(q: str, *, exact_title=False) -> str | None:
    if len(q) > MAX_TITLE_QUERY:
        raise bad_request('完整标题最多 2000 字符')
    tokens = _TOKEN_RE.findall(normalize_title(q))
    if not tokens or _CJK_RE.search(q):
        if exact_title and tokens:
            return None
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_QUERY", "message": "请输入英文关键词或已收录的中文方向名称"},
        )
    if len(q) > 300 or len(tokens) > 24:
        if exact_title:
            return None
        raise bad_request("关键词最多 300 字符、24 个英文词条；更长输入必须是已收录的完整标题")
    terms = ["\"" + tok + "\"" for tok in tokens]
    return " AND ".join(terms)


def search_predicate(q: str, match_expr: str | None):
    exact = Paper.title_norm == normalize_title(q)
    if match_expr is None:
        return exact
    # A normalized title index covers scientific Unicode without scanning the
    # entire paper table for every keystroke or weakening token boundaries.
    # Collect unique IDs once. An OR over three indexes makes SQLite recheck
    # the FTS lists for each candidate after its multi-index scan.
    return Paper.id.in_(union(
        select(Paper.id).where(exact),
        text("SELECT rowid FROM papers_fts WHERE papers_fts MATCH :match_q").columns(rowid=Integer),
        text("SELECT rowid FROM paper_titles_fts WHERE paper_titles_fts MATCH :match_q").columns(rowid=Integer),
    ))



def _search_page(db, filters, q, match_expr, sort, page, size):
    query = paper_query(db, filters).filter(search_predicate(q, match_expr))
    if match_expr is not None:
        query = query.params(match_q=match_expr)
    candidates = query
    score = literal(0.0).label('score')
    if match_expr is None:
        order = (Paper.id.desc(),) if sort == 'relevance' else PAPER_SORTS[sort]
    elif sort != 'relevance':
        order = PAPER_SORTS[sort]
    else:
        # Materialize once: a correlated MATCH would restart corpus-wide BM25
        # statistics for each candidate. Keep normalized-title-only matches.
        scores = (
            text('SELECT rowid AS paper_id, bm25(papers_fts, 8.0, 1.0) AS score '
                 'FROM papers_fts WHERE papers_fts MATCH :match_q')
            .columns(paper_id=Integer, score=Float)
            .cte('search_scores').prefix_with('MATERIALIZED')
        )
        query = query.outerjoin(scores, scores.c.paper_id == Paper.id)
        score = scores.c.score.label('score')
        exact_title = normalize_title(q)
        title_phrase = 'title : "' + ' '.join(_TOKEN_RE.findall(exact_title)) + '"'
        title_terms = 'title : (' + match_expr + ')'
        priority = text('''CASE
            WHEN papers.title_norm = :exact_title THEN 0
            WHEN (' ' || papers.title_norm || ' ') LIKE :normalized_phrase THEN 1
            WHEN papers.id IN (SELECT rowid FROM papers_fts WHERE papers_fts MATCH :title_phrase) THEN 1
            WHEN papers.id IN (SELECT rowid FROM paper_titles_fts WHERE paper_titles_fts MATCH :match_q) THEN 2
            WHEN papers.id IN (SELECT rowid FROM papers_fts WHERE papers_fts MATCH :title_terms) THEN 2
            ELSE 3 END''')
        query = query.params(exact_title=exact_title, normalized_phrase='% ' + exact_title + ' %',
                             title_phrase=title_phrase, title_terms=title_terms)
        order = (priority, text('score ASC'), Paper.id.desc())
    # The total and page share one eligibility/filter pass. An empty later page
    # still needs a count so it cannot be mistaken for a missing keyword match.
    rows = (query.with_entities(Paper.id, score, func.count().over().label('total'))
            .order_by(*order).offset((page - 1) * size).limit(size).all())
    total = rows[0][2] if rows else candidates.count() if page > 1 else 0
    ids = [row[0] for row in rows]
    page_scores = {row[0]: row[1] for row in rows}
    if ids and match_expr is not None and sort != 'relevance':
        # BM25 uses global term statistics even when rowid limits the output.
        # Date/year/citation sorting needs scores only for the displayed page.
        statement = text(
            'SELECT rowid, bm25(papers_fts, 8.0, 1.0) FROM papers_fts '
            'WHERE papers_fts MATCH :match_q AND rowid IN :page_ids'
        ).bindparams(bindparam('page_ids', expanding=True))
        page_scores.update(db.execute(statement, {'match_q': match_expr, 'page_ids': ids}).all())
    return total, ids, page_scores


def _search_authors(db, filters, q, sort, page, size):
    from app.services.author_search import author_match_expression, author_tokens

    expression = author_match_expression(author_tokens(q))
    if db.connection().exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='authors_search_fts'"
    ).first() is None:
        raise HTTPException(status_code=503, detail={
            'code': 'AUTHOR_INDEX_UNAVAILABLE', 'message': '作者索引尚未建立，请启用数据库初始化后重启本地后端'})
    matched = text("SELECT rowid FROM authors_search_fts WHERE authors_search_fts MATCH :author_match").columns(rowid=Integer)
    authorship = select(PaperAuthor.paper_id).where(PaperAuthor.author_id.in_(matched))
    query = paper_query(db, filters).filter(Paper.id.in_(authorship)).params(author_match=expression)
    actual_sort = "publication_desc" if sort == "relevance" else sort
    rows = (query.with_entities(Paper.id, func.count().over().label("total"))
            .order_by(*PAPER_SORTS[actual_sort]).offset((page - 1) * size).limit(size).all())
    total = rows[0][1] if rows else query.count() if page > 1 else 0
    ids = [row[0] for row in rows]
    by_id = {paper.id: paper for paper in db.query(Paper).filter(Paper.id.in_(ids)).all()} if ids else {}
    matched_names = {}
    if ids:
        names = (db.query(PaperAuthor.paper_id, Author.name).join(Author, Author.id == PaperAuthor.author_id)
                 .filter(PaperAuthor.paper_id.in_(ids), Author.id.in_(matched)).params(author_match=expression)
                 .order_by(PaperAuthor.paper_id, PaperAuthor.author_order, Author.id).all())
        for pid, name in names:
            if name not in matched_names.setdefault(pid, []):
                matched_names[pid].append(name)
    dirs, authors = directions_for(db, ids), authors_for(db, ids)
    return {"total": total, "page": page, "size": size,
            "items": [{**paper_card(by_id[pid], dirs, authors), "score": 0.0,
                       "matched_authors": sorted(matched_names.get(pid, []))} for pid in ids if pid in by_id],
            "match_mode": "author", "query_expansions": [], "effective_sort": actual_sort}


def _search_published(
    q: str = Query(..., max_length=MAX_TITLE_QUERY),
    filters: PaperFilters = Depends(paper_filters),
    sort: Literal["relevance", "publication_desc", "created_desc", "year_desc", "citation_desc"] = "relevance",
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
    match: Literal['auto', 'keywords', 'exact', 'fuzzy', 'author'] = 'auto',
):
    if page < 1 or not 1 <= size <= 100:
        raise bad_request("page>=1 且 1<=size<=100")
    if match == 'author':
        return _search_authors(db, filters, q, sort, page, size)
    rewritten = keyword_query(q)
    if match == 'auto' and rewritten != q:
        canonical = _search_published(q=rewritten, filters=filters, sort=sort, page=page, size=size, db=db, match='keywords')
        if canonical['total']:
            return {**canonical, 'query_rewrite': rewritten}
        try:
            original = _search_published(q=q, filters=filters, sort=sort, page=page, size=size, db=db, match='keywords')
        except HTTPException as error:
            if error.status_code != 400 or not isinstance(error.detail, dict) or error.detail.get('code') != 'EMPTY_QUERY':
                raise
            original = None
        if original and original['total']:
            return original
        result = _search_published(q=rewritten, filters=filters, sort=sort, page=page, size=size, db=db, match='fuzzy')
        return {**result, 'query_rewrite': rewritten}
    selected_topic = query_topic(q, match, db.query(Direction).filter(Direction.enabled == 1).all()) if _CJK_RE.search(q) else None
    if selected_topic is not None:
        query = paper_query(db, filters).filter(Paper.id.in_(
            db.query(PaperDirection.paper_id).filter(PaperDirection.direction_id == selected_topic.id)))
        actual_sort = 'publication_desc' if sort == 'relevance' else sort
        rows = (query.with_entities(Paper.id, func.count().over().label('total'))
                .order_by(*PAPER_SORTS[actual_sort]).offset((page-1)*size).limit(size).all())
        total = rows[0][1] if rows else query.count() if page > 1 else 0
        ids = [row[0] for row in rows]
        by_id = {p.id: p for p in db.query(Paper).filter(Paper.id.in_(ids)).all()} if ids else {}
        papers = [by_id[pid] for pid in ids if pid in by_id]
        directions, authors = directions_for(db, ids), authors_for(db, ids)
        return {'total':total, 'page':page, 'size':size,
                'items':[{**paper_card(p, directions, authors), 'score':0.0} for p in papers],
                'match_mode':'topic', 'query_expansions':[], 'effective_sort':actual_sort,
                'query_topic':{'code':selected_topic.code, 'name':selected_topic.name}}
    exact_title = normalize_title(q)
    extended = len(q) > 300 or len(_TOKEN_RE.findall(exact_title)) > 24 or bool(_CJK_RE.search(q))
    # Query validity must not change when a year/venue filter excludes a known
    # title. Keep the public A/B scope, matching the static reader's title map.
    exists = bool(extended and len(q) <= MAX_TITLE_QUERY and paper_query(db, PaperFilters())
                  .filter(Paper.title_norm == exact_title).first())
    match_expr = _build_match_expr(q, exact_title=exists or match == 'exact')
    if match == 'exact':
        match_expr = None
    match_mode = 'exact' if match == 'exact' else 'keywords'
    expansions = []
    total, ids, scores = 0, [], {}
    if match != 'fuzzy' or match_expr is None:
        total, ids, scores = _search_page(db, filters, q, match_expr, sort, page, size)
    if match_expr is not None and (match == 'fuzzy' or (match == 'auto' and total == 0)):
        vocabulary = title_vocabulary(db)
        tokens = list(dict.fromkeys(stemmer(token) for token in _TOKEN_RE.findall(exact_title)))
        groups = expand_tokens(tokens, vocabulary, raw_tokens=_TOKEN_RE.findall(exact_title))
        expansions = [{'token': token, 'alternatives': terms[1:]} for token, terms in zip(tokens, groups, strict=True) if len(terms) > 1]
        match_expr = ' AND '.join('(' + ' OR '.join('"' + term + '"' for term in terms) + ')' for terms in groups)
        total, ids, scores = _search_page(db, filters, q, match_expr, sort, page, size)
        match_mode = 'fuzzy'
    papers = db.query(Paper).filter(Paper.id.in_(ids)).all() if ids else []
    by_id = {p.id: p for p in papers}
    dirs = directions_for(db, ids)
    authors = authors_for(db, ids)
    items = []
    for p in (by_id[i] for i in ids if i in by_id):
        card = paper_card(p, dirs, authors)
        card["score"] = round(scores[p.id] or 0.0, 4)  # 保留旧响应 bm25 字段。
        items.append(card)
    return {"total": total, "page": page, "size": size, "items": items,
            "match_mode": match_mode, "query_expansions": expansions}


@router.get('')
def search(
    q: str = Query(..., max_length=MAX_TITLE_QUERY),
    filters: PaperFilters = Depends(paper_filters),
    sort: Literal['relevance', 'publication_desc', 'created_desc', 'year_desc', 'citation_desc'] = 'relevance',
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
    match: Literal['auto', 'keywords', 'exact', 'fuzzy', 'author'] = 'auto',
):
    from app.services.accepted_publications import REFERENCE_ROWS, accepted_references, match_accepted_references

    candidates = match_accepted_references(REFERENCE_ROWS, q, filters, match)
    references = accepted_references(db, candidates)
    actual_match = 'exact' if match == 'auto' and normalize_title(q) and match_accepted_references(references, q, filters, 'exact') else match
    result = _search_published(q=q, filters=filters, sort=sort, page=page, size=size, db=db, match=actual_match)
    topic = (result.get('query_topic') or {}).get('code')
    if topic:
        references = accepted_references(db, match_accepted_references(REFERENCE_ROWS, q, filters, match, topic))
    matched = match_accepted_references(references, q, filters, match, topic)
    return {**result, 'accepted_items': matched} if matched else result
