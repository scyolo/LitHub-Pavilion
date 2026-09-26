"""Refresh topic rules and links, preserving paper metadata and manual annotations."""
import csv
import re
from collections import Counter
from pathlib import Path

from app.api.filtering import PaperFilters, paper_query
from app.models import Direction, DirectionRule, Paper, PaperDirection
from app.services.tagging import load_rules, load_thresholds, score_text

LEGACY_MULTIMODAL = r"\bmulti[- ]?modal\b"
REFINED_MULTIMODAL = r"\bmulti[- ]?modal\b(?!\s+(?:optim(?:iz|is)ation|functions?|problems?|landscapes?))"


def _seeds(directory, filename):
    with (Path(directory) / filename).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def refresh_topic_rules(session, directory):
    topics = {row.code: row for row in session.query(Direction).all()}
    for seed in _seeds(directory, "directions.csv"):
        if seed["code"] not in topics:
            row = Direction(code=seed["code"], name=seed["name"], min_score=float(seed["min_score"]), enabled=int(seed["enabled"]))
            session.add(row)
            session.flush()
            topics[row.code] = row
    rules = {(row.direction_id, row.keyword): row for row in session.query(DirectionRule).all()}
    added = refined = 0
    for seed in _seeds(directory, "direction_rules.csv"):
        keyword = seed["keyword"]
        re.compile(keyword)
        direction = topics[seed["direction_code"]]
        key = (direction.id, keyword)
        if key in rules:
            continue
        if direction.code == "multimodal" and keyword == REFINED_MULTIMODAL:
            legacy = rules.get((direction.id, LEGACY_MULTIMODAL))
            if legacy is not None:
                if legacy.enabled == 1 and legacy.field == "both" and legacy.weight == 1:
                    legacy.keyword = keyword
                    rules[key] = legacy
                    refined += 1
                # A disabled or customized rule is an explicit local choice.
                continue
        row = DirectionRule(direction_id=direction.id, keyword=keyword, field=seed["field"], weight=float(seed["weight"]), enabled=int(seed["enabled"]))
        session.add(row)
        rules[key] = row
        added += 1
    session.flush()
    return {"rules_added": added, "rules_refined": refined}


def reindex_topics(session, directory):
    updated = refresh_topic_rules(session, directory)
    topics = {row.id: row for row in session.query(Direction).all()}
    rules, thresholds = load_rules(session), load_thresholds(session)
    papers = paper_query(session, PaperFilters()).with_entities(Paper.id, Paper.title, Paper.abstract).order_by(Paper.id).all()
    eligible = {row.id for row in papers}
    links = {(row.paper_id, row.direction_id): row for row in session.query(PaperDirection).all() if row.paper_id in eligible}
    before = Counter(topics[did].code for _, did in links)
    added, removed = Counter(), Counter()
    score_updates = 0
    for paper in papers:
        scores = score_text(rules, paper.title, paper.abstract)
        for direction_id, threshold in thresholds.items():
            key = (paper.id, direction_id)
            old = links.get(key)
            if old is not None and old.source == "manual":
                continue
            score = scores.get(direction_id, 0)
            if score >= threshold:
                if old is None:
                    session.add(PaperDirection(paper_id=paper.id, direction_id=direction_id, score=score, source="rule"))
                    added[topics[direction_id].code] += 1
                elif old.score != score:
                    old.score = score
                    score_updates += 1
            elif old is not None:
                session.delete(old)
                removed[topics[direction_id].code] += 1
    session.flush()
    current = [(pid, did) for pid, did in session.query(PaperDirection.paper_id, PaperDirection.direction_id).all() if pid in eligible]
    after = Counter(topics[did].code for _, did in current)
    tagged = {pid for pid, _ in current}
    codes = sorted(row.code for row in topics.values())
    return {**updated, "eligible_papers": len(papers), "untagged_papers": len(eligible - tagged),
            "before": {code: before[code] for code in codes}, "after": {code: after[code] for code in codes},
            "added_labels": {code: added[code] for code in codes}, "removed_labels": {code: removed[code] for code in codes},
            "updated_scores": score_updates}
