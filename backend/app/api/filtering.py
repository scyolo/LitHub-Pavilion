"""列表、检索和统计共用的只读 scope / 过滤 / 排序；不修改数据库结构。"""
import re
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.serializers import oa_link
from app.models import Direction, Paper, PaperDirection, Venue

LEVELS = ("A", "B")
VENUE_TYPES = ("conf", "journal")
PDF_STATUSES = ("pending", "downloaded", "failed", "closed")
PAPER_SORTS = {
    "publication_desc": (func.publication_sort_key(Paper.publication_date, Paper.year).desc(), Paper.id.desc()),
    "year_desc": (Paper.year.desc(), Paper.id.desc()),
    "citation_desc": (Paper.citation_count.desc(), Paper.id.desc()),
    "created_desc": (Paper.created_at.desc(), Paper.id.desc()),
}


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "INVALID_PARAM", "message": message})


@dataclass(frozen=True)
class PaperFilters:
    level: str | None = None
    type: str | None = None
    directions: tuple[str, ...] = ()
    venue: str | None = None
    year: int | None = None
    access: str | None = None
    pdf_status: str | None = None


def paper_filters(
    level: str | None = None,
    type: str | None = None,
    direction: str | None = None,
    venue: str | None = None,
    year: str | None = None,
    access: str | None = None,
    pdf_status: str | None = None,
) -> PaperFilters:
    for name, value, allowed in (
        ("level", level, LEVELS), ("type", type, VENUE_TYPES),
        ("access", access, ("oa", "official")), ("pdf_status", pdf_status, PDF_STATUSES),
    ):
        if value is not None and value not in allowed:
            raise bad_request(f"{name} 仅支持 {'|'.join(allowed)}")
    if year is not None and not re.fullmatch(r"[1-9][0-9]{3}", year):
        raise bad_request("year 必须是四位年份")
    directions = ()
    if direction is not None:
        directions = tuple(dict.fromkeys(code.strip() for code in direction.split(",")))
        if not all(directions):
            raise bad_request("direction 必须是非空 code，多个 code 使用逗号分隔")
    if venue is not None:
        venue = venue.strip()
        if not venue:
            raise bad_request("venue 必须是非空缩写")
    return PaperFilters(
        level=level, type=type, directions=directions, venue=venue,
        year=int(year) if year is not None else None, access=access, pdf_status=pdf_status,
    )


def venue_scope(filters: PaperFilters):
    """配置范围只取 level/type，不受论文方向、年份、OA 或是否有论文影响。"""
    conditions = [Venue.ccf_level.in_(LEVELS), Venue.type.in_(VENUE_TYPES)]
    if filters.level is not None:
        conditions.append(Venue.ccf_level == filters.level)
    if filters.type is not None:
        conditions.append(Venue.type == filters.type)
    return conditions


def _has_oa(oa_url: str | None, arxiv_id: str | None) -> int:
    return int(oa_link(oa_url, arxiv_id) is not None)


def has_oa_link(db: Session):
    """连接级 SQLite 纯函数：SQL 聚合与分页前过滤复用卡片的 URL 校验。

    不读取全表到 Python、不建表、不改 schema，也不解析 DNS 或请求链接。
    应用使用 SQLite/FTS5；连接归还池后函数保留，重复注册不会持久化到 DB。
    """
    connection = db.connection().connection.driver_connection
    connection.create_function("api_has_oa", 2, _has_oa, deterministic=True)
    return func.api_has_oa(Paper.oa_url, Paper.arxiv_id) == 1


def paper_query(db: Session, filters: PaperFilters):
    query = (
        db.query(Paper)
        .join(Venue, Paper.venue_id == Venue.id)
        .filter(Paper.ccf_level.in_(LEVELS), *venue_scope(filters))
    )
    if filters.level is not None:
        query = query.filter(Paper.ccf_level == filters.level)
    if filters.venue is not None:
        query = query.filter(Venue.abbr == filters.venue)
    if filters.year is not None:
        query = query.filter(Paper.year == filters.year)
    if filters.pdf_status is not None:
        query = query.filter(Paper.pdf_status == filters.pdf_status)
    if filters.directions:
        tagged_ids = (
            select(PaperDirection.paper_id)
            .join(Direction, PaperDirection.direction_id == Direction.id)
            .where(Direction.code.in_(filters.directions))
        )
        # IN/半连接保证多标签同维 OR，但一篇论文始终只计一次。
        query = query.filter(Paper.id.in_(tagged_ids))
    if filters.access is not None:
        oa = has_oa_link(db)
        query = query.filter(oa if filters.access == "oa" else ~oa)
    return query
