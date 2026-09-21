"""方向 / 会议期刊 / 规则 / 白名单接口（4.4）。"""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.filtering import PaperFilters, paper_filters, paper_query, venue_scope
from app.api.schemas import RuleCreateRequest, VenueUpsertRequest
from app.models import Direction, DirectionRule, Paper, PaperDirection, Venue

router = APIRouter(prefix="/api", tags=["taxonomies"])


@router.get("/directions")
def list_directions(db: Session = Depends(get_db)):
    counts = dict(
        paper_query(db, PaperFilters())
        .with_entities(PaperDirection.direction_id, func.count(Paper.id))
        .join(PaperDirection, PaperDirection.paper_id == Paper.id)
        .group_by(PaperDirection.direction_id)
        .all()
    )
    return {
        "items": [
            {"code": d.code, "name": d.name, "paper_count": counts.get(d.id, 0)}
            for d in db.query(Direction).filter(Direction.enabled == 1).all()
        ]
    }


@router.get("/venues")
def list_venues(level: str | None = None, direction: str | None = None, db: Session = Depends(get_db)):
    filters = paper_filters(level=level, direction=direction)
    query = db.query(Venue).filter(*venue_scope(filters))
    if filters.directions:
        sub = paper_query(db, filters).with_entities(Paper.venue_id)
        query = query.filter(Venue.id.in_(sub))
    venues = query.order_by(Venue.type, Venue.ccf_level, Venue.abbr).all()
    counts = dict(
        paper_query(db, PaperFilters())
        .with_entities(Paper.venue_id, func.count(Paper.id)).group_by(Paper.venue_id).all()
    )
    return {
        "items": [
            {
                "abbr": v.abbr,
                "name": v.name,
                "type": v.type,
                "level": v.ccf_level,
                "paper_count": counts.get(v.id, 0),
                "active": v.active,
            }
            for v in venues
        ]
    }


# ---- P2：Venue 管理（F-016） ----

@router.post("/venues", status_code=201)
def create_venue(body: VenueUpsertRequest, db: Session = Depends(get_db)):
    if db.query(Venue).filter(Venue.abbr == body.abbr).one_or_none():
        raise HTTPException(status_code=409, detail={"code": "DUPLICATE", "message": "abbr 已存在"})
    if db.query(Venue).filter(Venue.dblp_stream == body.dblp_stream).one_or_none():
        raise HTTPException(status_code=409, detail={"code": "DUPLICATE", "message": "dblp_stream 已存在"})
    venue = Venue(**body.model_dump())
    db.add(venue)
    db.commit()
    return {"abbr": venue.abbr}


@router.put("/venues/{abbr}")
def update_venue(abbr: str, body: VenueUpsertRequest, db: Session = Depends(get_db)):
    venue = db.query(Venue).filter(Venue.abbr == abbr).one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail={"code": "VENUE_NOT_FOUND", "message": "venue 不存在"})
    for key, value in body.model_dump().items():
        setattr(venue, key, value)
    db.commit()
    return {"abbr": venue.abbr, "active": venue.active}


@router.delete("/venues/{abbr}", status_code=204)
def deactivate_venue(abbr: str, db: Session = Depends(get_db)):
    venue = db.query(Venue).filter(Venue.abbr == abbr).one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail={"code": "VENUE_NOT_FOUND", "message": "venue 不存在"})
    venue.active = 0  # 停采而非物理删除，保护历史论文引用
    db.commit()


# ---- P2：方向规则管理（F-015） ----

@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    rows = (
        db.query(DirectionRule, Direction)
        .join(Direction, DirectionRule.direction_id == Direction.id)
        .all()
    )
    return {
        "items": [
            {
                "id": rule.id,
                "direction_code": d.code,
                "keyword": rule.keyword,
                "field": rule.field,
                "weight": rule.weight,
                "enabled": rule.enabled,
            }
            for rule, d in rows
        ]
    }


@router.post("/rules", status_code=201)
def create_rule(body: RuleCreateRequest, db: Session = Depends(get_db)):
    direction = db.query(Direction).filter(Direction.code == body.direction_code).one_or_none()
    if direction is None:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PARAM", "message": "direction_code 不存在"})
    try:
        re.compile(body.keyword)
    except re.error as exc:
        raise HTTPException(
            status_code=400, detail={"code": "INVALID_RULE", "message": f"正则非法: {exc}"}
        ) from exc
    rule = DirectionRule(
        direction_id=direction.id,
        keyword=body.keyword,
        field=body.field,
        weight=body.weight,
        enabled=body.enabled,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleCreateRequest, db: Session = Depends(get_db)):
    rule = db.query(DirectionRule).filter(DirectionRule.id == rule_id).one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail={"code": "RULE_NOT_FOUND", "message": "规则不存在"})
    direction = db.query(Direction).filter(Direction.code == body.direction_code).one_or_none()
    if direction is None:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PARAM", "message": "direction_code 不存在"})
    try:
        re.compile(body.keyword)
    except re.error as exc:
        raise HTTPException(
            status_code=400, detail={"code": "INVALID_RULE", "message": f"正则非法: {exc}"}
        ) from exc
    rule.direction_id = direction.id
    rule.keyword = body.keyword
    rule.field = body.field
    rule.weight = body.weight
    rule.enabled = body.enabled
    db.commit()
    return {"id": rule.id}


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(DirectionRule).filter(DirectionRule.id == rule_id).one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail={"code": "RULE_NOT_FOUND", "message": "规则不存在"})
    db.delete(rule)
    db.commit()
