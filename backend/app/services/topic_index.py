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
RULE_REFINEMENTS = {
    ("multimodal", LEGACY_MULTIMODAL): REFINED_MULTIMODAL,
    ("llm", r"\b(?:pre[- ]trained|parameter[- ]efficient)[- ](?:language )?models?\b"):
        r"\b(?:pre[- ]trained|parameter[- ]efficient)[- ]language[- ]models?\b",
    ("llm", r"\b(?:fine[- ]tuning|instruction[- ]following|reasoning models?)\b"):
        r"\b(?:instruction[- ]following|reasoning models?|fine[- ]tuning (?:large )?language models?)\b",
    ("cv", r"\b(?:object|anomaly|change) detection\b"):
        r"\b(?:object detection|(?:visual|image|video)[- ](?:anomaly|change)[- ]detection)\b",
    ("cv", r"\b(?:point clouds?|neural radiance fields?|3d|three[- ]dimensional)\b"):
        r"\b(?:point clouds?|neural radiance fields?|(?:3d|three[- ]dimensional)[- ](?:vision|reconstruction|segmentation|detection|generation|shapes?|scenes?))\b",
    ("nlp", r"\b(?:natural )?language\b"):
        r"\b(?:natural language|language[- ](?:models?|understanding|generation|resources?|translation))\b",
    ("retrieval", r"\b(?:search|ranking|recommendation)\b"):
        r"\b(?:(?:web|semantic|neural|document|passage)[- ]search|search engines?|(?:document|passage|retrieval)[- ]ranking|recommender systems?|recommendation systems?)\b",
    ("alignment", r"\balignment[- ](?:aware|based|free)\b"):
        r"\b(?:human|value|preference|safety|llm|language[- ]model)[- ]alignment\b",
}


def superseded_keywords(code, keyword):
    return [old for (topic, old), replacement in RULE_REFINEMENTS.items()
            if topic == code and replacement == keyword]


def _seeds(directory, filename):
    with (Path(directory) / filename).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def refresh_topic_name(direction, seed):
    if direction.code == "multimodal" and direction.name == "多模态学习" and seed["name"] == "多模态与视觉语言":
        direction.name = seed["name"]


def refresh_topic_rules(session, directory):
    topics = {row.code: row for row in session.query(Direction).all()}
    for seed in _seeds(directory, "directions.csv"):
        if seed["code"] not in topics:
            row = Direction(code=seed["code"], name=seed["name"], min_score=float(seed["min_score"]), enabled=int(seed["enabled"]))
            session.add(row)
            session.flush()
            topics[row.code] = row
        refresh_topic_name(topics[seed["code"]], seed)
    rules = {(row.direction_id, row.keyword): row for row in session.query(DirectionRule).all()}
    added = refined = 0
    for seed in _seeds(directory, "direction_rules.csv"):
        keyword = seed["keyword"]
        re.compile(keyword)
        direction = topics[seed["direction_code"]]
        key = (direction.id, keyword)
        legacy = next((rules[(direction.id, old)] for old in superseded_keywords(direction.code, keyword)
                       if (direction.id, old) in rules), None)
        if legacy is not None:
            replacement = rules.get(key)
            unmodified = legacy.enabled == 1 and legacy.field == 'both' and legacy.weight == 1
            if replacement is not None:
                if unmodified:
                    session.delete(legacy)
                    rules.pop((direction.id, legacy.keyword))
                    refined += 1
                elif replacement.enabled == 1 and replacement.field == 'both' and replacement.weight == 1:
                    replacement.enabled = 0
                    refined += 1
            elif unmodified:
                old_key = (direction.id, legacy.keyword)
                legacy.keyword = keyword
                rules.pop(old_key)
                rules[key] = legacy
                refined += 1
            # A disabled/customized predecessor is a local choice, not a missing rule.
            continue
        if key in rules:
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
    papers = paper_query(session, PaperFilters(), include_candidates=True).with_entities(Paper.id, Paper.title, Paper.abstract).order_by(Paper.id).all()
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
