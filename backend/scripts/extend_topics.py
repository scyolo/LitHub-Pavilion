"""Add adjacent research topics to existing A/B papers without changing venues or manual tags."""
import csv
import json
import re
import sqlite3
from datetime import datetime, timezone

from app.config import settings
from app.db import db_file_path, get_session
from app.models import Direction, DirectionRule, Paper, PaperDirection, Venue
from app.services.tagging import score_text

NEW_TOPIC_CODES = {"cv", "multimodal", "rl", "nlp", "retrieval", "alignment"}


def extend_topics(session) -> dict:
    with (settings.seeds_dir / "directions.csv").open(encoding="utf-8-sig", newline="") as source:
        topic_seeds = [row for row in csv.DictReader(source) if row["code"] in NEW_TOPIC_CODES]
    with (settings.seeds_dir / "direction_rules.csv").open(encoding="utf-8-sig", newline="") as source:
        rule_seeds = [row for row in csv.DictReader(source) if row["direction_code"] in NEW_TOPIC_CODES]

    topics = {}
    for seed in topic_seeds:
        direction = session.query(Direction).filter(Direction.code == seed["code"]).one_or_none()
        if direction is None:
            direction = Direction(code=seed["code"], name=seed["name"], min_score=float(seed["min_score"]), enabled=1)
            session.add(direction)
            session.flush()
        topics[seed["code"]] = direction

    for seed in rule_seeds:
        direction = topics[seed["direction_code"]]
        re.compile(seed["keyword"])
        existing = session.query(DirectionRule).filter(
            DirectionRule.direction_id == direction.id, DirectionRule.keyword == seed["keyword"]
        ).one_or_none()
        if existing is None:
            session.add(DirectionRule(direction_id=direction.id, keyword=seed["keyword"],
                                      field=seed["field"], weight=float(seed["weight"]), enabled=1))
    session.flush()
    enabled_topics = {direction.id: direction for direction in topics.values() if direction.enabled}
    rules = [
        (rule.direction_id, re.compile(rule.keyword, re.IGNORECASE), rule.weight, rule.field)
        for rule in session.query(DirectionRule).filter(
            DirectionRule.direction_id.in_(enabled_topics), DirectionRule.enabled == 1
        ).all()
    ]
    added = {code: 0 for code in topics}
    eligible = session.query(Paper.id, Paper.title, Paper.abstract).join(Venue, Paper.venue_id == Venue.id).filter(
        Paper.ccf_level.in_(("A", "B")), Venue.ccf_level.in_(("A", "B")), Venue.type.in_(("conf", "journal"))
    ).all()
    links = {(row.paper_id, row.direction_id) for row in session.query(PaperDirection).filter(
        PaperDirection.direction_id.in_(enabled_topics)
    ).all()}
    for paper_id, title, abstract in eligible:
        for direction_id, score in score_text(rules, title, abstract).items():
            direction = enabled_topics.get(direction_id)
            if direction is None or score < direction.min_score or (paper_id, direction_id) in links:
                continue
            session.add(PaperDirection(paper_id=paper_id, direction_id=direction_id, score=score, source="rule"))
            links.add((paper_id, direction_id))
            added[direction.code] += 1
    session.commit()
    return {"eligible_papers": len(eligible), "added_labels": added}


def main() -> None:
    path = db_file_path()
    backup = None
    if path and path.exists():
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / ("before-topic-extension-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".db")
        with sqlite3.connect(str(path)) as source, sqlite3.connect(str(backup)) as target:
            source.backup(target)
    with get_session() as session:
        result = extend_topics(session)
    result["backup"] = str(backup.resolve()) if backup else None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
