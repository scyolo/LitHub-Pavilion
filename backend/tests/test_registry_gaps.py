import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.backfill_registry_gaps import (
    book_units,
    eligible_item,
    journal_units,
    reusable_unit,
    series_units,
    unit_key,
)


def test_journal_plan_covers_verified_electronic_issn_even_when_source_is_populated():
    venue = SimpleNamespace(
        abbr="JASA",
        name="The Journal of the Acoustical Society of America",
        type="journal",
        issn="0001-4966",
    )
    units = journal_units({"JASA": venue}, 2023, 2026)
    assert {u["issn"] for u in units} == {"0001-4966", "1520-8524"}
    assert all(u["year_from"] == 2023 and u["year_to"] == 2026 for u in units)


def test_journal_candidate_requires_exact_source_and_final_issue_year():
    venue = SimpleNamespace(
        abbr="JASA",
        name="The Journal of the Acoustical Society of America",
        type="journal",
        issn="0001-4966",
    )
    spec = {"kind": "journal", "year_from": 2025, "year_to": 2026}
    row = {
        "DOI": "10.1121/10.0038128",
        "title": ["Acoustic research"],
        "ISSN": ["1520-8524"],
        "type": "journal-article",
        "container-title": [venue.name],
        "published-online": {"date-parts": [[2024]]},
        "published-print": {"date-parts": [[2025]]},
    }
    assert eligible_item(row, venue, spec)
    assert not eligible_item(
        {**row, "container-title": ["JASA Express Letters"]}, venue, spec
    )
    assert not eligible_item({**row, "ISSN": ["9999-9999"]}, venue, spec)
    assert not eligible_item(
        {**row, "published-print": {"date-parts": [[2027]]}}, venue, spec
    )
    assert not eligible_item({**row, "type": "dataset"}, venue, spec)


def test_conference_candidate_uses_exact_main_container_and_event_year():
    venue = SimpleNamespace(
        abbr="ICRA",
        name="International Conference on Robotics and Automation",
        type="conf",
        ccf_level="B",
    )
    title = "2026 IEEE International Conference on Robotics and Automation (ICRA)"
    spec = {"kind": "conference", "title": title, "year": 2026}
    row = {
        "DOI": "10.1109/icra57385.2026.11697085",
        "type": "proceedings-article",
        "container-title": [title],
        "title": ["Robotic research"],
        "published-print": {"date-parts": [[2027]]},
    }
    assert eligible_item(row, venue, spec)
    assert not eligible_item(
        {**row, "container-title": [title + " Workshops"]}, venue, spec
    )
    assert not eligible_item(
        {**row, "container-title": [title.replace("2026", "2025")]}, venue, spec
    )
    assert not eligible_item({**row, "DOI": "10.1145/unrelated"}, venue, spec)


def test_resume_never_treats_dry_run_partial_or_bounded_search_as_complete():
    assert reusable_unit({"applied": True, "status": "registry_enumerated"}, True)
    assert not reusable_unit({"applied": False, "status": "registry_enumerated"}, True)
    for status in ("running", "partial", "failed", "bounded_search_finished"):
        assert not reusable_unit({"applied": True, "status": status}, True)
    assert not reusable_unit(
        {
            "applied": True,
            "status": "registry_enumerated",
            "counts": {"identity_conflicts": 1},
        },
        True,
    )


def test_resume_identity_is_stable_but_separates_source_year_and_serial():
    spec = {
        "kind": "journal",
        "venue": "JASA",
        "issn": "1520-8524",
        "year_from": 2023,
        "year_to": 2026,
    }
    assert unit_key(spec) == unit_key({**spec, "status": "running", "counts": {}})
    assert unit_key(spec) != unit_key({**spec, "issn": "0001-4966"})
    assert unit_key(spec) != unit_key({**spec, "year_to": 2025})


@pytest.mark.parametrize("apply", [False, True])
def test_gap_run_preserves_existing_metadata_and_imports_each_new_doi_once(
    db, engine, tmp_path, monkeypatch, apply
):
    from app.models import Paper, Venue
    from app.services.publisher_metadata import apply_items
    from scripts import backfill_registry_gaps as script

    venue = Venue(
        abbr="JASA",
        name="The Journal of the Acoustical Society of America",
        issn="0001-4966",
        type="journal",
        ccf_level="B",
        active=1,
    )
    db.add(venue)
    db.commit()
    row = {
        "DOI": "10.1121/existing",
        "title": ["Existing acoustic research"],
        "author": [{"given": "Jane", "family": "Smith"}],
        "ISSN": ["1520-8524"],
        "container-title": [venue.name],
        "type": "journal-article",
        "published-print": {"date-parts": [[2026, 5, 1]]},
    }
    apply_items(db, [row], [2026])
    existing = db.query(Paper).one()
    existing.note += "\nUser research note"
    db.commit()
    preserved = (existing.id, existing.title, existing.note, existing.updated_at)
    calls = []

    @asynccontextmanager
    async def client():
        yield None

    async def fetch(_client, issn, year_from, year_to, *, on_page):
        calls.append(issn)
        items = [
            {**row, "title": ["An upstream title edit"]},
            {**row, "DOI": "10.1121/new", "title": ["New acoustic wave analysis"]},
            {
                **row,
                "DOI": "10.1121/wrong-source",
                "container-title": ["Unrelated Journal"],
            },
        ]
        on_page(issn, 1, len(items), len(items), items)

    monkeypatch.setattr(script, "make_client", client)
    monkeypatch.setattr(script, "fetch_journal", fetch)
    args = SimpleNamespace(
        database=Path(engine.url.database),
        output=tmp_path / "report",
        resume=False,
        venue=["JASA"],
        journals=True,
        discovery=None,
        year_from=2023,
        year_to=2026,
        apply=apply,
        workers=2,
    )
    report = asyncio.run(script.run(args))
    db.expire_all()
    current = db.get(Paper, preserved[0])
    assert (current.id, current.title, current.note, current.updated_at) == preserved
    assert set(calls) == {"0001-4966", "1520-8524"}
    assert db.query(Paper).count() == (2 if apply else 1)
    assert db.query(Paper).filter(Paper.doi == "10.1121/wrong-source").count() == 0
    assert sum(u["counts"].get("new", 0) for u in report["units"]) == int(apply)


@pytest.mark.parametrize("manual", [False, True])
def test_official_batch_tags_imported_paper_and_preserves_manual_direction(
    db, sample_paper, sample_direction, manual
):
    from app.models import DirectionRule, PaperDirection
    from scripts.collect_official_inventories import tag_inventory_records

    key = "https://papers.nips.cc/paper_files/paper/2024/hash/test-Abstract.html"
    sample_paper.publisher_key = key
    db.add(
        DirectionRule(
            direction_id=sample_direction.id,
            keyword="speculative decoding",
            weight=1,
            field="title",
            enabled=1,
        )
    )
    if manual:
        db.add(
            PaperDirection(
                paper_id=sample_paper.id,
                direction_id=sample_direction.id,
                source="manual",
                score=42,
            )
        )
    db.commit()
    assert (
        tag_inventory_records(db, [SimpleNamespace(extra={"publisher_key": key})]) == 1
    )
    relation = (
        db.query(PaperDirection)
        .filter_by(paper_id=sample_paper.id, direction_id=sample_direction.id)
        .one()
    )
    assert relation.source == ("manual" if manual else "rule")
    if manual:
        assert relation.score == 42


def test_book_plan_and_admission_require_exact_parent_doi_and_event_year(tmp_path):
    venue = SimpleNamespace(
        abbr="TCC", name="Theory of Cryptography Conference", type="conf", ccf_level="B"
    )
    parent = {
        "DOI": "10.1007/978-3-032-12287-2",
        "type": "book",
        "title": ["Theory of Cryptography"],
        "subtitle": ["TCC 2025, Proceedings, Part I"],
        "ISBN": ["9783032122872"],
    }
    (tmp_path / "parents.json").write_text(
        json.dumps(
            {
                "venue": "TCC",
                "items": [
                    parent,
                    parent,
                    {
                        **parent,
                        "DOI": "10.1007/978-3-000-00000-0",
                        "subtitle": ["TCC 2025 Workshops, Proceedings"],
                    },
                ],
            }
        ),
        "utf8",
    )
    units = book_units(tmp_path, {"TCC": venue}, 2023, 2026)
    assert len(units) == 1 and units[0]["year"] == 2025
    row = {
        "DOI": parent["DOI"] + "_1",
        "type": "book-chapter",
        "container-title": ["Lecture Notes in Computer Science", parent["title"][0]],
        "title": ["Secure cryptographic protocols"],
        "_catalog_book_parent": parent,
        "published-print": {"date-parts": [[2026]]},
    }
    assert eligible_item(row, venue, units[0])
    assert not eligible_item(
        {**row, "DOI": "10.1007/978-3-000-00000-0_1"}, venue, units[0]
    )
    assert not eligible_item({**row, "_catalog_book_parent": {}}, venue, units[0])


def test_series_plan_preserves_conference_issue_gate():
    venue = SimpleNamespace(
        abbr="POPL",
        name="Principles of Programming Languages",
        type="conf",
        ccf_level="A",
    )
    (spec,) = series_units({"POPL": venue}, 2023, 2026)
    assert spec["issn"] == "2475-1421"
    row = {
        "DOI": "10.1145/3632895",
        "type": "journal-article",
        "title": ["Type theory"],
        "container-title": ["Proceedings of the ACM on Programming Languages"],
        "ISSN": [spec["issn"]],
        "issue": "POPL",
        "volume": "8",
        "published-print": {"date-parts": [[2024, 1, 2]]},
    }
    assert eligible_item(row, venue, spec)
    assert not eligible_item({**row, "issue": "ICFP"}, venue, spec)
    assert not eligible_item({**row, "issue": "1"}, venue, spec)


def test_new_front_matter_headings_do_not_inflate_public_paper_coverage():
    from app.services.publication_admission import nonresearch_title

    for title in ("Issue Information", "Note from the Editor", "ICRA 2026 Commentary"):
        assert nonresearch_title(title)
    for title in (
        "Using issue information to predict software faults",
        "A commentary on robot learning",
        "ICRA 2026 Commentary Analysis for Robot Navigation",
    ):
        assert not nonresearch_title(title)


def test_checkpoint_retries_windows_reader_lock_without_losing_prior_report(
    tmp_path, monkeypatch
):
    from scripts import backfill_registry_gaps as script

    path = tmp_path / "report.json"
    path.write_text('{"status":"previous"}', "utf8")
    real_replace = Path.replace
    attempts = []

    def replace(source, target):
        attempts.append(source)
        assert json.loads(path.read_text("utf8"))["status"] == "previous"
        if len(attempts) < 3:
            raise PermissionError("Windows reader still holds the checkpoint")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(script.time, "sleep", lambda _delay: None)
    script.save_report(path, {"status": "finished"})
    assert len(attempts) == 3
    assert json.loads(path.read_text("utf8")) == {"status": "finished"}
