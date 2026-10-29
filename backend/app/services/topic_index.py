"""Refresh topic rules and links, preserving paper metadata and manual annotations."""
import csv
import re
from collections import Counter
from pathlib import Path

from app.api.filtering import PaperFilters, paper_query
from app.models import Direction, DirectionRule, DirectionVenue, Paper, PaperDirection, Venue
from app.services.tagging import add_venue_scores, load_rules, load_thresholds, load_venue_rules, score_text

LEGACY_MULTIMODAL = r"\bmulti[- ]?modal\b"
REFINED_MULTIMODAL = r"\bmulti[- ]?modal\b(?!\s+(?:optim(?:iz|is)ation|functions?|problems?|landscapes?))"
RULE_REFINEMENTS = {
    ("specdec", "draft model"):
        r"(?s)\A(?=.*\bdraft[- ]models?\b)(?=.*\b(?:llms?|language[- ]models?|tokens?|decod\w*|verification)\b).+",
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
    ("systems", r"\b(?:operating|distributed|storage|file|cloud|database)[- ]systems?\b"):
        r"\b(?:operating|distributed|(?<!battery )(?<!energy )(?<!power )storage|file|cloud|database)[- ]systems?\b",
    ("network", r"\b(?:computer|communication|data[- ]?cent(?:er|re)|mobile|wireless|cellular|satellite|optical|underwater|sensor|vehicular|mesh|overlay|content[- ]delivery)[- ]networks?\b"):
        r"\b(?:computer|data[- ]?cent(?:er|re)|wireless|cellular|satellite|optical|underwater|sensor|vehicular|mesh|overlay|content[- ]delivery)[- ]networks?\b",
    ("network", r"\b(?:network|networking)[- ](?:protocols?|topolog\w*|measurement|management|slicing|traffic|virtualization|functions?|congestion)\b"):
        r"\b(?:network|networking)[- ](?:protocols?|measurement|management|slicing|traffic|virtualization|functions?|congestion)\b",
    ("network", r"\b(?:software[- ]defined networking|sdn|network function virtualization|nfv|openflow|p4|programmable switches?|smart[- ]?nics?|dpdk)\b"):
        r"\b(?:software[- ]defined networking|sdn|network function virtualization|nfv|openflow|p4[- ](?:programmable|based|language|switch(?:es)?|data[- ]plane)|programmable switches?|smart[- ]?nics?|dpdk)\b",
    ("network", r"\b(?:tcp|quic|ipv6|dns|rdma|roce|infiniband)\b"):
        r"\b(?:quic|ipv6|dns|rdma|roce|infiniband)\b",
    ("network", r"\b(?:5g|6g|lte|wifi|wi[- ]fi|802\.11|massive mimo|spectrum sharing|cognitive radio|radio access networks?)\b"):
        r"\b(?:(?:5g|6g)[- ](?:networks?|nr|new radio|core|ran|wireless|systems?|enabled|iot|mec)|lte[- ](?:networks?|systems?|advanced)|wifi|wi[- ]fi|802\.11|massive mimo|spectrum sharing|cognitive radio|radio access networks?)\b",
    ("systems", r"\b(?:rdma|nvme|ssds?|solid[- ]state drives?|cxl|disaggregated memory|memory disaggregation|storage disaggregation)\b"):
        r"\b(?:rdma|nvme|solid[- ]state drives?|cxl|disaggregated memory|memory disaggregation|storage disaggregation)\b",
    ("systems", r"\b(?:key[- ]value stores?|kv[- ]?stores?|object storage|block storage|erasure coding|deduplication|lsm[- ]trees?|b[- ]trees?|write amplification)\b"):
        r"\b(?:key[- ]value stores?|kv[- ]?stores?|object storage|block storage|erasure coding|(?:storage|data|backup) deduplication|lsm[- ]trees?|b[- ]trees?|write amplification)\b",
    ("systems", r"\b(?:cluster|job|workload|task) scheduling\b"):
        r"\b(?:cluster|job|workload) scheduling\b",
    ("architecture", r"\b(?:multi[- ]core|many[- ]core|superscalar|out[- ]of[- ]order|branch predictor|speculative execution|cache hierarchy|memory hierarchy)\b"):
        r"\b(?:multi[- ]core|many[- ]core|superscalar|out[- ]of[- ]order (?:execution|processors?|cores?|pipelines?|cpus?)|branch predictor|speculative execution|cache hierarchy|memory hierarchy)\b",
    ("architecture", r"\b(?:hardware[- ]software co[- ]design|architecture[- ]aware|hardware[- ]aware|microarchitectural)\b"):
        r"\b(?:hardware[- ]software co[- ]design|microarchitectural)\b",
    ("security", r"\b(?:authentication|authorization|access control|sandboxing|intrusion detection|fuzzing|software fault isolation|memory safety)\b"):
        r"\b(?:authentication|authorization|access control|(?:browser|javascript|web|android|mobile|application|software) sandbox\w*|intrusion detection|fuzzing|software fault isolation|memory safety)\b",
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
            expected_weight = float(seed["weight"])
            unmodified = legacy.enabled == 1 and legacy.field == seed["field"] and legacy.weight == expected_weight
            if replacement is not None:
                if unmodified:
                    session.delete(legacy)
                    rules.pop((direction.id, legacy.keyword))
                    refined += 1
                elif replacement.enabled == 1 and replacement.field == seed["field"] and replacement.weight == expected_weight:
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


def refresh_topic_venues(session, directory):
    """Add missing venue→direction priors; never overwrite local weights or enabled flags."""
    directions = {row.code: row.id for row in session.query(Direction).all()}
    venues = {row.abbr: row.id for row in session.query(Venue).all()}
    existing = {
        (direction_id, venue_id)
        for direction_id, venue_id in session.query(DirectionVenue.direction_id, DirectionVenue.venue_id).all()
    }
    added = 0
    for seed in _seeds(directory, "direction_venues.csv"):
        direction_id = directions.get(seed["direction_code"])
        venue_id = venues.get(seed["venue_abbr"])
        if direction_id is None or venue_id is None or (direction_id, venue_id) in existing:
            continue
        session.add(DirectionVenue(
            direction_id=direction_id, venue_id=venue_id,
            weight=float(seed["weight"]), enabled=int(seed["enabled"]),
        ))
        existing.add((direction_id, venue_id))
        added += 1
    session.flush()
    return {"venue_rules_added": added}


def reindex_topics(session, directory):
    updated = {**refresh_topic_rules(session, directory), **refresh_topic_venues(session, directory)}
    topics = {row.id: row for row in session.query(Direction).all()}
    rules, thresholds = load_rules(session), load_thresholds(session)
    venue_rules = load_venue_rules(session)
    papers = paper_query(session, PaperFilters(), include_candidates=True).with_entities(Paper.id, Paper.title, Paper.abstract, Paper.venue_id).order_by(Paper.id).all()
    eligible = {row.id for row in papers}
    links = {(row.paper_id, row.direction_id): row for row in session.query(PaperDirection).all() if row.paper_id in eligible}
    before = Counter(topics[did].code for _, did in links)
    added, removed = Counter(), Counter()
    score_updates = 0
    for paper in papers:
        scores = score_text(rules, paper.title, paper.abstract)
        add_venue_scores(scores, paper.venue_id, venue_rules)
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
