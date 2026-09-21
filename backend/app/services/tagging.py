"""方向打标规则引擎（4.2）：title 命中数×2×weight + abstract 命中数×1×weight，≥min_score 入选。

manual 标签永不删除/覆盖（A9）：重打标只重算 source='rule' 行；
插入 rule 行前跳过已存在 manual 的方向（避免复合主键冲突，P0-2）。
全部数据库操作走 ORM 会话（参数化），不拼接 SQL 字符串。
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Direction, DirectionRule, PaperDirection


def _compile_rules(
    rules: list[tuple[int, str, float, str]],
) -> list[tuple[int, re.Pattern, float, str]]:
    """(direction_id, pattern, weight, field)；坏正则防御性跳过。"""
    compiled = []
    for direction_id, keyword, weight, field_name in rules:
        try:
            compiled.append((direction_id, re.compile(keyword, re.IGNORECASE), weight, field_name))
        except re.error:
            continue
    return compiled


def load_rules(session: Session) -> list[tuple[int, re.Pattern, float, str]]:
    rows = session.execute(
        select(DirectionRule.direction_id, DirectionRule.keyword, DirectionRule.weight, DirectionRule.field)
        .join(Direction, Direction.id == DirectionRule.direction_id)
        .where(DirectionRule.enabled == 1, Direction.enabled == 1)
    ).all()
    return _compile_rules(rows)


def load_thresholds(session: Session) -> dict[int, float]:
    rows = session.execute(
        select(Direction.id, Direction.min_score).where(Direction.enabled == 1)
    ).all()
    return {d: float(m or 2.0) for d, m in rows}


def score_text(
    rules: list[tuple[int, re.Pattern | str, float, str]],
    title: str,
    abstract: str | None,
) -> dict[int, float]:
    """返回 direction_id → 分数。按 4.2 公式：title 命中数×2×weight + abstract 命中数×1×weight。

    规则项可为已编译 Pattern 或正则字符串（字符串按 IGNORECASE 现场编译）。
    """
    scores: dict[int, float] = {}
    for direction_id, pattern, weight, field_name in rules:
        if isinstance(pattern, str):
            pattern = re.compile(pattern, re.IGNORECASE)
        title_hits = len(pattern.findall(title or "")) if field_name in ("title", "both") else 0
        abstract_hits = (
            len(pattern.findall(abstract)) if field_name in ("abstract", "both") and abstract else 0
        )
        if title_hits or abstract_hits:
            scores[direction_id] = scores.get(direction_id, 0.0) + 2.0 * weight * title_hits + 1.0 * weight * abstract_hits
    return scores


def apply_tagging(
    session: Session,
    paper_id: int,
    title: str,
    abstract: str | None,
    rules: list[tuple[int, re.Pattern, float, str]],
    thresholds: dict[int, float],
) -> list[int]:
    """重算该论文的 rule 标签（保留 manual），返回最终 direction_id 列表。"""
    scores = score_text(rules, title, abstract)

    manual_ids = {
        row[0]
        for row in session.execute(
            select(PaperDirection.direction_id).where(
                PaperDirection.paper_id == paper_id,
                PaperDirection.source == "manual",
            )
        ).all()
    }

    existing = {row.direction_id: row for row in session.query(PaperDirection).filter(PaperDirection.paper_id == paper_id).all()}
    selected = {
        direction_id: score for direction_id, score in scores.items()
        if direction_id in thresholds and score >= thresholds[direction_id]
    }
    for direction_id, row in existing.items():
        if row.source == "rule" and direction_id not in selected:
            session.delete(row)
    for direction_id, score in selected.items():
        if direction_id in manual_ids:
            continue
        row = existing.get(direction_id)
        if row is None:
            session.add(PaperDirection(paper_id=paper_id, direction_id=direction_id, score=score, source="rule"))
        else:
            row.score = score

    session.flush()
    final = session.execute(
        select(PaperDirection.direction_id).where(PaperDirection.paper_id == paper_id)
    ).scalars().all()
    return sorted(set(final) | manual_ids)
