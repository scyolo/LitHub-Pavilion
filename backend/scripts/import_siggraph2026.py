"""Import the SIGGRAPH 2026 main-conference parent inventory (10.1145/3799902).

Mirrors the verified 2025 path in scripts.backfill_remaining_proceedings: the
publisher-deposited parent proceedings and its child articles are enumerated
exactly, validated per article, and applied through apply_catalog_page with the
official parent attached. No PDFs, no fuzzy matching, no full-coverage claim.
"""

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.collectors.acm_proceedings import validate_article
from app.db import _make_engine
from app.models import Venue
from app.services.catalog_backfill import apply_catalog_page
from app.services.tagging import load_rules, load_thresholds
from scripts.reconcile_papers import _backup


def run(args):
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    parent = inventory["parent"]
    if parent["DOI"] != "10.1145/3799902":
        raise ValueError("Unexpected SIGGRAPH 2026 parent")
    # validate_article reads the standard Crossref date fields; the cached
    # inventory stores them under "published" already.
    items = []
    excluded = 0
    for item in inventory["items"]:
        if not str(item.get("DOI", "")).startswith(parent["DOI"] + "."):
            excluded += 1
            continue
        validate_article(item, parent, inventory["container"], 2026)
        items.append({**item, "_official_siggraph_parent": parent})
    report = {
        "applied": args.apply,
        "pdf_downloads": 0,
        "full_coverage_verified": False,
        "units": [
            {
                "venue": "SIGGRAPH",
                "year": 2026,
                "source": "https://api.crossref.org/works/10.1145/3799902",
                "matched": len(items),
                "excluded_other_parents": excluded,
                "complete": False,
                "note": "Publisher-deposited main conference proceedings identity; not all SIGGRAPH tracks or TOG papers.",
            }
        ],
    }
    if args.apply:
        if not args.database.is_file():
            raise ValueError("Existing database required")
        report["backup"] = str(_backup(args.database.resolve()))
        engine = _make_engine("sqlite:///" + args.database.resolve().as_posix())
        try:
            with Session(engine) as db:
                rules, thresholds = load_rules(db), load_thresholds(db)
                db.query(Venue).filter_by(
                    abbr="SIGGRAPH", type="conf", active=1
                ).one()
                result = apply_catalog_page(db, items, [2026], rules, thresholds)
                report["units"][0]["import"] = result["counts"]
                report["units"][0]["conflicts"] = result["conflicts"][:20]
        finally:
            engine.dispose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--apply", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()
