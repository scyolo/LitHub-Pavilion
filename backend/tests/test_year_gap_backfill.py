import json
from types import SimpleNamespace

from scripts.backfill_conference_year_gaps import plan_units


def test_queue_requires_exact_catalog_and_edition_and_skips_present_scope(tmp_path):
    v = SimpleNamespace(
        abbr="CHI",
        name="ACM Conference on Human Factors in Computing Systems",
        type="conf",
        ccf_level="A",
    )
    good = {
        "DOI": "10.1145/123.456",
        "type": "proceedings-article",
        "container-title": [
            "Proceedings of the CHI Conference on Human Factors in Computing Systems"
        ],
        "event": {"acronym": "CHI '24"},
    }
    bad = {
        **good,
        "container-title": [
            "Proceedings of the CHI Conference on Human Factors in Computing Systems Companion"
        ],
    }
    (tmp_path / "discovery.json").write_text(
        json.dumps(
            {"venue": "CHI", "year": 2024, "queries": [{"items": [good, bad, good]}]}
        ),
        encoding="utf-8",
    )
    result = plan_units(tmp_path, {"CHI": v}, set())
    assert len(result) == 1 and result[0]["year"] == 2024
    assert result[0]["exact_filter"].startswith("container-title:")
    assert plan_units(tmp_path, {"CHI": v}, {("CHI", 2024)}) == []
    good["event"]["acronym"] = "CHI '23"
    (tmp_path / "discovery.json").write_text(
        json.dumps({"venue": "CHI", "year": 2024, "queries": [{"items": [good]}]}),
        encoding="utf-8",
    )
    assert plan_units(tmp_path, {"CHI": v}, set()) == []
