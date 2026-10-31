"""FTS5 英文全文检索：参数绑定、有限词数、共享 scope 和稳定排序。"""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Float, Integer, literal, select, text, union
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.filtering import PAPER_SORTS, PaperFilters, bad_request, paper_filters, paper_query
from app.api.serializers import authors_for, directions_for, paper_card
from app.models import Direction, Paper, PaperDirection
from app.cleaning import normalize_title
from app.services.fuzzy_terms import expand_tokens
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



def _search_published(
    q: str = Query(..., max_length=MAX_TITLE_QUERY),
    filters: PaperFilters = Depends(paper_filters),
    sort: Literal["relevance", "publication_desc", "created_desc", "year_desc", "citation_desc"] = "relevance",
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
    match: Literal['auto', 'keywords', 'exact', 'fuzzy'] = 'auto',
):
    if page < 1 or not 1 <= size <= 100:
        raise bad_request("page>=1 且 1<=size<=100")
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
        result = _search_published(q=rewritten, filters=filters, sort=sort, page=page, size=size, db=db, match='auto')
        return {**result, 'query_rewrite': rewritten}
    selected_topic = query_topic(q, match, db.query(Direction).filter(Direction.enabled == 1).all()) if _CJK_RE.search(q) else None
    if selected_topic is not None:
        query = paper_query(db, filters).filter(Paper.id.in_(
            db.query(PaperDirection.paper_id).filter(PaperDirection.direction_id == selected_topic.id)))
        actual_sort = 'publication_desc' if sort == 'relevance' else sort
        total = query.count()
        papers = query.order_by(*PAPER_SORTS[actual_sort]).offset((page-1)*size).limit(size).all()
        ids = [p.id for p in papers]
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
    query = paper_query(db, filters).filter(search_predicate(q, match_expr))
    if match_expr is not None:
        query = query.params(match_q=match_expr)
    total = query.count()
    match_mode = 'exact' if match == 'exact' else 'keywords'
    expansions = []
    if match_expr is not None and (match == 'fuzzy' or (match == 'auto' and total == 0)):
        vocabulary = db.connection().exec_driver_sql('SELECT term, doc FROM paper_titles_vocab ORDER BY term').all()
        tokens = list(dict.fromkeys(stemmer(token) for token in _TOKEN_RE.findall(exact_title)))
        groups = expand_tokens(tokens, vocabulary, raw_tokens=_TOKEN_RE.findall(exact_title))
        expansions = [{'token': token, 'alternatives': terms[1:]} for token, terms in zip(tokens, groups, strict=True) if len(terms) > 1]
        match_expr = ' AND '.join('(' + ' OR '.join('"' + term + '"' for term in terms) + ')' for terms in groups)
        query = paper_query(db, filters).filter(search_predicate(q, match_expr)).params(match_q=match_expr)
        total = query.count()
        match_mode = 'fuzzy'
    if match_expr is None:
        score = literal(0.0).label('score')
        order = (Paper.id.desc(),) if sort == 'relevance' else PAPER_SORTS[sort]
    else:
        # A correlated MATCH reinitializes FTS5 (including corpus-wide BM25
        # statistics) for every candidate. Materialize the matching scores once
        # before joining; LEFT JOIN keeps normalized-title-only matches visible.
        scores = (
            text("SELECT rowid AS paper_id, bm25(papers_fts, 8.0, 1.0) AS score "
                 "FROM papers_fts WHERE papers_fts MATCH :match_q")
            .columns(paper_id=Integer, score=Float)
            .cte("search_scores")
            .prefix_with("MATERIALIZED")
        )
        query = query.outerjoin(scores, scores.c.paper_id == Paper.id)
        score = scores.c.score.label("score")
        title_phrase = 'title : "' + " ".join(_TOKEN_RE.findall(exact_title)) + '"'
        title_terms = "title : (" + match_expr + ")"
        priority = text("""CASE
            WHEN papers.title_norm = :exact_title THEN 0
            WHEN (' ' || papers.title_norm || ' ') LIKE :normalized_phrase THEN 1
            WHEN papers.id IN (SELECT rowid FROM papers_fts WHERE papers_fts MATCH :title_phrase) THEN 1
            WHEN papers.id IN (SELECT rowid FROM paper_titles_fts WHERE paper_titles_fts MATCH :match_q) THEN 2
            WHEN papers.id IN (SELECT rowid FROM papers_fts WHERE papers_fts MATCH :title_terms) THEN 2
            ELSE 3 END""")
        query = query.params(exact_title=exact_title, normalized_phrase='% ' + exact_title + ' %', title_phrase=title_phrase, title_terms=title_terms)
        order = (priority, text("score ASC"), Paper.id.desc()) if sort == "relevance" else PAPER_SORTS[sort]
    rows = (
        query.with_entities(Paper.id, score)
        .order_by(*order)
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    ids = [row[0] for row in rows]
    scores = {row[0]: row[1] for row in rows}
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
    match: Literal['auto', 'keywords', 'exact', 'fuzzy'] = 'auto',
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
