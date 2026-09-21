"""统计接口：共享论文 scope，所有论文计数在 SQL 中聚合，不载入全表。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.filtering import PaperFilters, has_oa_link, paper_filters, paper_query, venue_scope
from app.api.serializers import abstract_text
from app.models import CrawlLog, Direction, Paper, PaperDirection, Venue

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _count_if(condition):
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _directions(db: Session, query) -> list[dict]:
    counts = (
        query.with_entities(PaperDirection.direction_id.label("direction_id"), func.count(Paper.id).label("paper_count"))
        .join(PaperDirection, PaperDirection.paper_id == Paper.id)
        .group_by(PaperDirection.direction_id)
        .subquery()
    )
    rows = (
        db.query(Direction.code, Direction.name, func.coalesce(counts.c.paper_count, 0))
        .outerjoin(counts, counts.c.direction_id == Direction.id)
        .filter(or_(Direction.enabled == 1, counts.c.paper_count > 0))
        .order_by(Direction.code)
        .all()
    )
    return [{"code": code, "name": name, "paper_count": count} for code, name, count in rows]


def _last_crawl(db: Session) -> dict | None:
    run = (
        db.query(CrawlLog)
        .filter(CrawlLog.venue_id.is_(None), CrawlLog.task_type.in_(("weekly", "backfill")))
        .order_by(CrawlLog.started_at.desc(), CrawlLog.id.desc())
        .first()
    )
    if run is None:
        return None
    failed_units = (
        db.query(func.count(CrawlLog.id))
        .filter(
            CrawlLog.run_id == run.run_id, CrawlLog.venue_id.isnot(None),
            CrawlLog.status.in_(("failed", "partial")),
        )
        .scalar()
    )
    return {
        "run_id": run.run_id,
        # 老采集器可能给部分失败的总日志写 success；只修正展示，不回写日志。
        "status": "partial" if run.status == "success" and failed_units else run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "papers_new": run.papers_new,
        "papers_updated": run.papers_updated,
        "failed_units": failed_units,
        "error": run.error,
    }


@router.get("/dashboard")
def dashboard(filters: PaperFilters = Depends(paper_filters), db: Session = Depends(get_db)):
    """真实本地论文统计，过滤维度之间 AND，direction 多 code 之间 OR。

    annual.year 使用数据库论文归属年 Paper.year，不是入库日期 created_at，
    也不从 DBLP key 推断出版年；2023 至当前 UTC 年补齐零计数。
    recent_count 是最近 7 天 created_at 入库数，不使用 publication_date。
    directions 为可重叠多标签计数，不能相加当作论文总数。
    configured_venues 按 level/type 配置范围计数（含停采 venue）；venues 的
    paper_count/years 与所有其它论文指标使用同一过滤结果，可包含零数据项。
    last_crawl 为最近 weekly/backfill 总日志，failed_units 包括 failed/partial 子日志。
    """
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()
    query = paper_query(db, filters)
    oa = has_oa_link(db)
    connection = db.connection().connection.driver_connection
    connection.create_function("api_has_abstract", 1, lambda value: int(abstract_text(value) is not None), deterministic=True)
    # SQLite julianday 会处理 UTC/时区偏移；避免 ISO 字符串格式影响七天边界。
    recent = func.julianday(Paper.created_at).between(
        func.julianday((now - timedelta(days=7)).isoformat()), func.julianday(generated_at),
    )
    summary = query.with_entities(
        func.count(Paper.id).label("total"),
        _count_if(oa).label("with_oa_link"),
        _count_if(func.api_has_abstract(Paper.abstract) == 1).label("with_abstract"),
        _count_if(Paper.venue_confirmed == 1).label("confirmed_count"),
        _count_if(recent).label("recent_count"),
        _count_if(Paper.ccf_level == "A").label("level_a"),
        _count_if(Paper.ccf_level == "B").label("level_b"),
        _count_if(Venue.type == "conf").label("conf"),
        _count_if(Venue.type == "journal").label("journal"),
        func.count(func.distinct(Paper.venue_id)).label("venues_with_papers"),
    ).one()
    annual = {year: {"year": year, "A": 0, "B": 0, "total": 0} for year in range(2023, now.year + 1)}
    for year, level, count in (
        query.with_entities(Paper.year, Paper.ccf_level, func.count(Paper.id))
        .filter(Paper.year.between(2023, now.year))
        .group_by(Paper.year, Paper.ccf_level)
        .all()
    ):
        annual[year][level] = count
        annual[year]["total"] += count
    directions = _directions(db, query)
    configured_venues = db.query(func.count(Venue.id)).filter(*venue_scope(filters)).scalar()
    counts = (
        query.with_entities(Paper.venue_id.label("venue_id"), func.count(Paper.id).label("paper_count"))
        .group_by(Paper.venue_id)
        .subquery()
    )
    venue_query = (
        db.query(Venue, func.coalesce(counts.c.paper_count, 0))
        .outerjoin(counts, counts.c.venue_id == Venue.id)
        .filter(*venue_scope(filters))
    )
    if filters.venue is not None:
        venue_query = venue_query.filter(Venue.abbr == filters.venue)
    years_by_venue: dict[int, list[dict]] = {}
    for venue_id, year, count in (
        query.with_entities(Paper.venue_id, Paper.year, func.count(Paper.id))
        .group_by(Paper.venue_id, Paper.year)
        .order_by(Paper.venue_id, Paper.year)
        .all()
    ):
        years_by_venue.setdefault(venue_id, []).append({"year": year, "count": count})
    venues = [
        {
            "id": venue.id, "abbr": venue.abbr, "name": venue.name, "type": venue.type,
            "level": venue.ccf_level, "ccf_area": venue.ccf_area, "active": venue.active,
            "paper_count": count, "years": years_by_venue.get(venue.id, []),
        }
        for venue, count in venue_query.order_by(Venue.type, Venue.ccf_level, Venue.abbr).all()
    ]
    return {
        "generated_at": generated_at,
        "total": summary.total,
        "with_oa_link": summary.with_oa_link,
        "with_abstract": summary.with_abstract,
        "confirmed_count": summary.confirmed_count,
        "recent_count": summary.recent_count,
        "by_level": {"A": summary.level_a, "B": summary.level_b},
        "by_type": {"conf": summary.conf, "journal": summary.journal},
        "annual": list(annual.values()),
        "directions": directions,
        "venues": venues,
        "configured_venues": configured_venues,
        "venues_with_papers": summary.venues_with_papers,
        "last_crawl": _last_crawl(db),
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """保留旧响应字段，同时使用与新接口相同的 A/B scope 和 OA 判定。"""
    query = paper_query(db, PaperFilters())
    total, pdf_archived, with_link = query.with_entities(
        func.count(Paper.id), _count_if(Paper.pdf_status == "downloaded"), _count_if(has_oa_link(db)),
    ).one()
    by_direction = {row["code"]: row["paper_count"] for row in _directions(db, query)}
    by_level = {"A": 0, "B": 0}
    by_level.update(dict(query.with_entities(Paper.ccf_level, func.count(Paper.id)).group_by(Paper.ccf_level).all()))
    by_year = dict(query.with_entities(Paper.year, func.count(Paper.id)).group_by(Paper.year).order_by(Paper.year).all())
    last_run = (
        db.query(CrawlLog.started_at)
        .filter(CrawlLog.task_type == "weekly", CrawlLog.venue_id.is_(None))
        .order_by(CrawlLog.started_at.desc(), CrawlLog.id.desc())
        .first()
    )
    return {
        "total": total,
        "by_direction": by_direction,
        "by_level": by_level,
        "by_year": by_year,
        "pdf_archived": pdf_archived,
        "with_oa_link": with_link,
        "last_crawl_at": last_run[0] if last_run else None,
    }
