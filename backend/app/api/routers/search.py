"""FTS5 英文全文检索：参数绑定、有限词数、共享 scope 和稳定排序。"""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.filtering import PAPER_SORTS, PaperFilters, bad_request, paper_filters, paper_query
from app.api.serializers import authors_for, directions_for, paper_card
from app.models import Paper

router = APIRouter(prefix="/api/search", tags=["search"])

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]")


def _build_match_expr(q: str) -> str:
    if len(q) > 300:
        raise bad_request("q 最多 300 字符、24 个英文词条")
    tokens = _TOKEN_RE.findall(q)
    if not tokens or _CJK_RE.search(q):
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_QUERY", "message": "请输入可检索的英文词条；暂不支持中文检索"},
        )
    if len(tokens) > 24:
        raise bad_request("q 最多 300 字符、24 个英文词条")
    return " AND ".join('"' + tok + '"' for tok in tokens)


@router.get("")
def search(
    q: str = Query(..., max_length=300),
    filters: PaperFilters = Depends(paper_filters),
    sort: Literal["relevance", "created_desc", "year_desc", "citation_desc"] = "relevance",
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
):
    if page < 1 or not 1 <= size <= 100:
        raise bad_request("page>=1 且 1<=size<=100")
    match_expr = _build_match_expr(q)
    # 显式 Paper.venue_id == Venue.id 的共享查询，不把 Paper.id 当 venue ID。
    query = (
        paper_query(db, filters)
        .filter(text("papers.id IN (SELECT rowid FROM papers_fts WHERE papers_fts MATCH :match_q)"))
        .params(match_q=match_expr)
    )
    total = query.count()
    score = text("(SELECT bm25(papers_fts) FROM papers_fts WHERE rowid = papers.id AND papers_fts MATCH :match_q) AS score")
    order = (text("score ASC"), Paper.id.desc()) if sort == "relevance" else PAPER_SORTS[sort]
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
        card["score"] = round(scores[p.id], 4)  # 保留旧响应 bm25 字段。
        items.append(card)
    return {"total": total, "page": page, "size": size, "items": items}
