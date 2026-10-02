"""Reconcile the remaining WWW25/Middleware23/SIGGRAPH25 scopes from saved primary evidence.

Only metadata/links; no fetches or PDF access. Default is dry-run. Partial source
inventories, title changes and author mismatches remain explicit in the report.
"""

import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.cleaning import normalize_title
from app.collectors.acm_open_toc import parse_open_toc, restore_verified_subtitles
from app.collectors.acm_proceedings import match_official_track, validate_article
from app.db import _make_engine
from app.models import Paper, Venue
from app.services.catalog_backfill import apply_catalog_page
from app.services.publisher_import import apply_records
from app.services.tagging import apply_tagging, load_rules, load_thresholds
from scripts.audit_www2025_schedule import parse_posters
from scripts.reconcile_papers import _backup


def run(args):
    units, selected = [], {}
    configs = [
        (
            "WWW",
            2025,
            args.www_evidence / "inventory-WWW-2025.json",
            "www25-sigweb.html",
            "WWW '25: Proceedings of the ACM on Web Conference 2025",
            "https://www.sigweb.org/toc/www25a.html",
        ),
        (
            "Middleware",
            2023,
            args.evidence / "inventory-Middleware.json",
            "middleware23-toc.html",
            "Middleware '23: Proceedings of the 24th International Middleware Conference",
            "https://middleware-conf.github.io/2023/open-toc/",
        ),
    ]
    for venue, year, inventory_path, filename, heading, source in configs:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        page = args.evidence / filename
        official = parse_open_toc(
            page.read_text(encoding="utf-8"), inventory["parent"]["DOI"], heading
        )
        all_count = len(official)
        if venue == "WWW":
            posters = parse_posters(
                (args.www_evidence / "www2025-posters.html").read_text(encoding="utf-8")
            )
            research = {normalize_title(row["title"]) for row in posters}
            official = [
                row for row in official if normalize_title(row["title"]) in research
            ]
        # The TOC directly supplies DOI: do not accept a same-title different DOI.
        doi_titles = {row["doi"]: normalize_title(row["title"]) for row in official}
        matched_inventory = {
            **inventory,
            "items": [item for item in inventory["items"] if item["DOI"] in doi_titles],
        }
        matched_inventory["items"], subtitle_count = restore_verified_subtitles(
            matched_inventory["items"], official
        )
        records, issues = match_official_track(matched_inventory, official)
        selected[venue] = records
        units.append(
            {
                "venue": venue,
                "year": year,
                "source": source,
                "sha256": hashlib.sha256(page.read_bytes()).hexdigest(),
                "official_toc_count": all_count,
                "selected_research_count": len(official),
                "matched": len(records),
                "verified_subtitles_restored": subtitle_count,
                "unresolved": issues,
                "complete": False,
            }
        )
    inventory = json.loads(
        (args.evidence / "inventory-SIGGRAPH.json").read_text(encoding="utf-8")
    )
    parent = inventory["parent"]
    if parent["DOI"] != "10.1145/3721238":
        raise ValueError("Unexpected SIGGRAPH parent")
    items = []
    excluded = 0
    for item in inventory["items"]:
        if not item.get("DOI", "").startswith(parent["DOI"] + "."):
            excluded += 1
            continue
        validate_article(item, parent, inventory["container"], 2025)
        items.append({**item, "_official_siggraph_parent": parent})
    units.append(
        {
            "venue": "SIGGRAPH",
            "year": 2025,
            "source": "https://api.crossref.org/works/10.1145/3721238",
            "matched": len(items),
            "excluded_other_parents": excluded,
            "complete": False,
            "note": "Publisher-deposited main conference proceedings identity; not all SIGGRAPH tracks or TOG papers.",
        }
    )
    report = {
        "applied": args.apply,
        "pdf_downloads": 0,
        "full_coverage_verified": False,
        "units": units,
    }
    if args.apply:
        if not args.database.is_file():
            raise ValueError("Existing database required")
        report["backup"] = str(_backup(args.database.resolve()))
        engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
        try:
            with Session(engine) as db:
                rules, thresholds = load_rules(db), load_thresholds(db)
                for unit in units[:2]:
                    venue = (
                        db.query(Venue)
                        .filter_by(abbr=unit["venue"], type="conf", active=1)
                        .one()
                    )
                    unit["import"] = apply_records(db, selected[venue.abbr], venue)
                    for raw in selected[venue.abbr]:
                        paper = (
                            db.query(Paper)
                            .filter_by(
                                doi=raw.doi, venue_id=venue.id, year=unit["year"]
                            )
                            .one_or_none()
                        )
                        if paper is not None and paper.title_norm == normalize_title(
                            raw.title
                        ):
                            evidence = "Official research-track list: " + unit["source"]
                            if evidence not in (paper.note or ""):
                                paper.note = (paper.note or "") + "\n" + evidence
                            apply_tagging(
                                db,
                                paper.id,
                                paper.title,
                                paper.abstract,
                                rules,
                                thresholds,
                            )
                    db.commit()
                units[2]["import"] = apply_catalog_page(
                    db, items, [2025], rules, thresholds
                )
        finally:
            engine.dispose()
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                **report,
                "units": [
                    {k: v for k, v in u.items() if k != "unresolved"} for u in units
                ],
            },
            ensure_ascii=False,
        )
    )
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--www-evidence", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()
