"""Historical AI-direction backfill through official venue catalogues (2017-2022).

Project coverage starts in 2023 with complete CCF A/B volumes; earlier years
were only federated-directed. This unit keeps titles that meet the transformer,
LLM, inference or speculative-decoding direction thresholds plus a small list of
famous AI papers whose generic titles miss those rules, then adds three curated
ACL Anthology records whose collection XML is absent. Only configured CCF A/B
venues are admitted and no PDF is fetched.
"""

import argparse
import asyncio
import html
import io
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.cleaning import clean_author_name, normalize_title
from app.collectors.http_client import make_client
from app.collectors.publisher_toc import _raw, fetch_official_inventory
from app.db import _make_engine
from app.models import Direction, Paper, PaperDirection, Venue
from app.ratelimit import AsyncTokenBucket
from app.services.publication_admission import nonresearch_title
from app.services.publisher_import import apply_records
from app.services.tagging import apply_tagging, load_rules, load_thresholds, score_text
from scripts.reconcile_papers import _backup

TARGET_CODES = ("llm", "inference", "specdec", "transformer")
UNITS = (
    *(("NeurIPS", year) for year in range(2017, 2023)),
    *(("ICML", year) for year in range(2017, 2023)),
    *(("JMLR", year) for year in range(2017, 2023)),
    *(("ACL", year) for year in (2020, 2021, 2022)),
    *(("EMNLP", year) for year in (2020, 2021, 2022)),
    *(("NAACL", year) for year in (2021, 2022)),
    *(("CVPR", year) for year in (2021, 2022)),
    ("ICCV", 2021),
    ("ECCV", 2020),
    ("ECCV", 2022),
)
CURATED = (
    {
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "venue": "NAACL",
        "year": 2019,
        "publisher_key": "https://aclanthology.org/N19-1423/",
        "authors": ["Devlin, Jacob", "Chang, Ming-Wei", "Lee, Kenton", "Toutanova, Kristina"],
    },
    {
        "title": "Transformer-XL: Attentive Language Models beyond a Fixed-Length Context",
        "venue": "ACL",
        "year": 2019,
        "publisher_key": "https://aclanthology.org/P19-1285/",
        "authors": [
            "Dai, Zihang", "Yang, Zhilin", "Yang, Yiming",
            "Carbonell, Jaime G.", "Le, Quoc", "Salakhutdinov, Ruslan",
        ],
    },
    {
        "title": "Deep Contextualized Word Representations",
        "venue": "NAACL",
        "year": 2018,
        "publisher_key": "https://aclanthology.org/N18-1202/",
        "authors": [
            "Peters, Matthew E.", "Neumann, Mark", "Iyyer, Mohit", "Gardner, Matt",
            "Clark, Christopher", "Lee, Kenton", "Zettlemoyer, Luke",
        ],
    },
    {
        "title": "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks",
        "venue": "EMNLP",
        "year": 2019,
        "publisher_key": "https://aclanthology.org/D19-1410/",
        "authors": ["Reimers, Nils", "Gurevych, Iryna"],
    },
)
CLASSICS = (
    "Attention Is All You Need",
    "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
    "Transformer-XL: Attentive Language Models beyond a Fixed-Length Context",
    "Deep Contextualized Word Representations",
    "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks",
    "XLNet: Generalized Autoregressive Pretraining for Language Understanding",
    "Language Models are Few-Shot Learners",
    "Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer",
    "Training language models to follow instructions with human feedback",
    "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
    "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
    "Big Bird: Transformers for Longer Sequences",
    "Swin Transformer: Hierarchical Vision Transformer using Shifted Windows",
    "Training data-efficient image transformers & distillation through attention",
    "MLP-Mixer: An all-MLP Architecture for Vision",
    "GLaM: Efficient Scaling of Language Models with Mixture-of-Experts",
    "Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity",
    "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    "Learning Transferable Visual Models From Natural Language Supervision",
    "Zero-Shot Text-to-Image Generation",
    "Denoising Diffusion Probabilistic Models",
    "Diffusion Models Beat GANs on Image Synthesis",
    "End-to-End Object Detection with Transformers",
    "NeRF: Representing Scenes as Neural Radiance Fields for View Synthesis",
    "Masked Autoencoders Are Scalable Vision Learners",
    "A ConvNet for the 2020s",
    "Neural Ordinary Differential Equations",
    "Blockwise Parallel Decoding for Deep Autoregressive Models",
)
# Generic titles that miss the direction rules but are canonical in these directions.
CLASSIC_SELECTION = frozenset(normalize_title(title) for title in CLASSICS)


async def fetch_with_retry(client, limiter, venue, year, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            return await fetch_official_inventory(
                client, limiter, venue, year, allow_missing_authors=True
            )
        except httpx.HTTPStatusError as error:
            if attempt == attempts or error.response.status_code < 500:
                raise
        except httpx.TransportError:
            if attempt == attempts:
                raise
        await asyncio.sleep(5 * attempt)


def _chunks(values, size=400):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _clean_authors(values):
    authors, seen = [], set()
    for value in values:
        name = clean_author_name((value or "").strip())
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            authors.append(name)
    return authors


_ATTRIBUTE = re.compile(
    r'([A-Za-z][A-Za-z0-9:_-]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))'
)


def _meta_values(text, name):
    values = []
    for tag in re.findall(r"<meta\b[^>]*>", text, re.I):
        attrs = {
            key.casefold(): next((value for value in groups if value), "")
            for key, *groups in _ATTRIBUTE.findall(tag)
        }
        if attrs.get("name", "").casefold() == name.casefold() and "content" in attrs:
            values.append(html.unescape(attrs["content"]).strip())
    return values


def _meta(text, name):
    values = _meta_values(text, name)
    return values[0] if values else None


async def fetch_curated(client, limiter, entry):
    """Verify a curated record against the official landing page metadata."""
    await limiter.acquire()
    response = await client.get(entry["publisher_key"])
    response.raise_for_status()
    if "html" not in response.headers.get("content-type", "").lower():
        raise ValueError("Curated publisher identity is not an HTML landing page")
    page_title = _meta(response.text, "citation_title")
    page_authors = _meta_values(response.text, "citation_author")
    publication = _meta(response.text, "citation_publication_date") or ""
    if page_title is None or not page_authors:
        raise ValueError("Curated landing page lacks title/author metadata")
    if normalize_title(page_title) != normalize_title(entry["title"]):
        raise ValueError("Curated landing page title mismatch")
    if {clean_author_name(name).casefold() for name in page_authors} != {
        name.casefold() for name in entry["authors"]
    }:
        raise ValueError("Curated landing page author mismatch")
    if not publication.startswith(str(entry["year"])):
        raise ValueError("Curated landing page year mismatch")
    raw = _raw(entry["publisher_key"], page_title, page_authors, entry["year"])
    raw.authors = _clean_authors(raw.authors)
    return raw


async def run(args):
    if not args.database.is_file():
        raise ValueError("Existing database required")
    args.output.mkdir(parents=True, exist_ok=True)
    engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "applied": args.apply,
        "pdf_downloads": 0,
        "scope": "CCF A/B official volumes 2017-2022; transformer/LLM/inference/specdec titles",
        "units": [],
    }
    if args.apply:
        report["backup"] = str(_backup(args.database.resolve()))
    limiter = AsyncTokenBucket(1)

    def save():
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    try:
        with Session(engine) as db:
            venues = {
                venue.abbr: venue
                for venue in db.query(Venue).filter(
                    Venue.active == 1, Venue.ccf_level.in_(("A", "B"))
                )
            }
            targets = {
                row.code: row.id
                for row in db.query(Direction).filter(Direction.code.in_(TARGET_CODES))
            }
            if set(targets) != set(TARGET_CODES):
                raise ValueError("Run scripts.seed to register the AI directions first")
            rules, thresholds = load_rules(db), load_thresholds(db)
            db.expunge_all()

        selected, curated = [], []
        async with make_client() as client:
            for abbr, year in UNITS:
                if args.venue and abbr not in args.venue:
                    continue
                if args.year and year not in args.year:
                    continue
                venue = venues.get(abbr)
                if venue is None:
                    continue
                unit = {"venue": abbr, "year": year}
                stats = Counter()
                try:
                    records = await fetch_with_retry(client, limiter, venue, year)
                except Exception as error:  # noqa: BLE001 - keep scanning
                    unit.update(
                        status="unavailable",
                        error=f"{type(error).__name__}: {str(error)[:160]}",
                    )
                    report["units"].append(unit)
                    save()
                    continue
                if not records:
                    unit.update(status="no_official_volume", official=0)
                    report["units"].append(unit)
                    save()
                    continue
                stats["official"] = len(records)
                kept = []
                for raw in records:
                    if raw.year != year:
                        stats["year_mismatch"] += 1
                        continue
                    raw.authors = _clean_authors(raw.authors)
                    if not raw.authors or nonresearch_title(normalize_title(raw.title)):
                        stats["nonresearch_or_no_authors"] += 1
                        continue
                    scores = score_text(rules, raw.title, None)
                    matched = {
                        code for code in TARGET_CODES
                        if scores.get(targets[code], 0) >= thresholds[targets[code]]
                    }
                    if not matched and normalize_title(raw.title) not in CLASSIC_SELECTION:
                        continue
                    stats.update(matched)
                    kept.append(raw)
                stats["selected"] = len(kept)
                unit.update(status="ok", counts=dict(stats))
                report["units"].append(unit)
                selected.extend((abbr, raw) for raw in kept)
                save()
                print(json.dumps(unit, ensure_ascii=False), flush=True)

            for entry in CURATED:
                if args.venue and entry["venue"] not in args.venue:
                    continue
                if args.year and entry["year"] not in args.year:
                    continue
                unit = {"venue": entry["venue"], "year": entry["year"], "curated": entry["title"]}
                raw = None
                for attempt in range(1, 4):
                    try:
                        raw = await fetch_curated(client, limiter, entry)
                        break
                    except httpx.TransportError as error:
                        if attempt == 3:
                            unit.update(status="unavailable", error=f"{type(error).__name__}: {str(error)[:160]}")
                        else:
                            await asyncio.sleep(5 * attempt)
                    except Exception as error:  # noqa: BLE001 - report and continue
                        unit.update(status="unavailable", error=f"{type(error).__name__}: {str(error)[:160]}")
                        break
                if raw is not None:
                    unit.update(status="ok", publisher_key=raw.extra["publisher_key"])
                    curated.append((entry["venue"], raw))
                report["units"].append(unit)
                save()
                print(json.dumps(unit, ensure_ascii=False), flush=True)

        by_venue = {}
        for abbr, raw in [*selected, *curated]:
            by_venue.setdefault(abbr, []).append(raw)
        total = sum(len(records) for records in by_venue.values())
        report["selected"] = total
        report["selected_by_venue"] = {
            abbr: len(records) for abbr, records in by_venue.items()
        }
        conflicts = []
        if args.apply and total:
            with Session(engine) as db:
                rules, thresholds = load_rules(db), load_thresholds(db)
                totals = Counter()
                imported = {}
                for abbr, records in by_venue.items():
                    result = apply_records(db, records, venues[abbr])
                    totals.update(result["counts"])
                    conflicts.extend(result["conflicts"])
                    imported[abbr] = result["counts"]
                    keys = [
                        raw.extra["publisher_key"]
                        for raw in records
                        if raw.extra.get("publisher_key")
                    ]
                    tagged = 0
                    for chunk in _chunks(keys):
                        for paper in db.query(Paper).filter(Paper.publisher_key.in_(chunk)).all():
                            apply_tagging(
                                db, paper.id, paper.title, paper.abstract, rules, thresholds
                            )
                            tagged += 1
                    imported[abbr]["tagged"] = tagged
                db.commit()
                report["import"] = dict(totals)
                report["import_by_venue"] = imported
                report["conflicts"] = conflicts[:50]
                report["conflict_total"] = len(conflicts)

        with Session(engine) as db:
            report["coverage_by_venue"] = {
                abbr: db.query(Paper).filter(Paper.venue_id == venues[abbr].id).count()
                for abbr in by_venue
            }
            if args.apply:
                keys = [
                    raw.extra["publisher_key"]
                    for records in by_venue.values()
                    for raw in records
                    if raw.extra.get("publisher_key")
                ]
                confirmed, unique, selected_ids = 0, set(), set()
                for chunk in _chunks(keys):
                    rows = db.query(Paper.id, Paper.publisher_key, Paper.venue_confirmed).filter(
                        Paper.publisher_key.in_(chunk)
                    ).all()
                    for paper_id, key, flag in rows:
                        selected_ids.add(paper_id)
                        unique.add(key)
                        confirmed += flag == 1
                report["verified_unique_publisher_keys"] = len(unique)
                report["verified_confirmed"] = confirmed
                targets = {
                    row.code: row.id
                    for row in db.query(Direction).filter(Direction.code.in_(TARGET_CODES))
                }
                tagged_papers = {code: set() for code in TARGET_CODES}
                for chunk in _chunks(sorted(selected_ids)):
                    rows = db.query(PaperDirection.paper_id, PaperDirection.direction_id).filter(
                        PaperDirection.paper_id.in_(chunk),
                        PaperDirection.direction_id.in_(list(targets.values())),
                    ).all()
                    reverse = {direction_id: code for code, direction_id in targets.items()}
                    for paper_id, direction_id in rows:
                        tagged_papers[reverse[direction_id]].add(paper_id)
                report["tagged_by_direction"] = {
                    code: len(ids) for code, ids in tagged_papers.items()
                }
                report["classics"] = {
                    title: db.query(Paper).filter(
                        Paper.title_norm == normalize_title(title)
                    ).count()
                    for title in CLASSICS
                }
                report["verified"] = (
                    total > 0
                    and not conflicts
                    and len(unique) == total
                    and confirmed == total
                )
    finally:
        engine.dispose()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps({
        "applied": report["applied"],
        "selected": report.get("selected", 0),
        "by_venue": report.get("selected_by_venue"),
        "import": report.get("import"),
        "verified": report.get("verified", False),
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--venue", action="append")
    parser.add_argument("--year", type=int, action="append")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
