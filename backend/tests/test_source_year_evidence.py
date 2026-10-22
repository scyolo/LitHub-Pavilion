import pytest

from app.services.source_coverage import source_year_checks, zero_year_summary


def source():
    return {
        "abbr": "Meeting",
        "primary_years": {"2024": 2},
        "associated_years": {"2025": 1},
    }


def evidence(status="not_scheduled", **extra):
    return {
        "status": status,
        "note": "Official calendar specifies this edition.",
        "checked_at": "2026-10-21",
        "evidence_url": "https://publisher.example/calendar",
        **extra,
    }


def test_explained_zero_is_still_zero_and_associated_years_are_not_gaps():
    row = source()
    row["year_checks"] = source_year_checks(
        row, {"year_checks": {"2023": evidence()}}, {"Meeting"}
    )
    assert set(row["year_checks"]) == {"2023", "2026"}
    assert row["year_checks"]["2023"]["status"] == "not_scheduled"
    assert row["year_checks"]["2026"]["status"] == "unverified"
    assert "checked_at" not in row["year_checks"]["2026"]
    assert zero_year_summary([row]) == {
        "zero_source_year_units": 2,
        "zero_year_status_counts": {"not_scheduled": 1, "unverified": 1},
    }


def test_new_records_supersede_an_old_pending_publication_annotation():
    row = source()
    notes = {"year_checks": {"2024": evidence("publication_pending")}}
    checks = source_year_checks(row, notes, {"Meeting"})
    assert "2024" not in checks
    assert row["primary_years"] == {"2024": 2}


@pytest.mark.parametrize("change", [
    {"evidence_url": "javascript:alert(1)"},
    {"evidence_url": "https://user:secret@publisher.example/"},
    {"checked_at": "2026-02-30"},
    {"status": "complete"},
    {"note": ""},
    {"note": "x" * 1001},
    {"status": "joint_edition", "canonical_venue": "Outside"},
    {"status": "joint_edition", "canonical_venue": "Meeting"},
])
def test_source_evidence_cannot_fabricate_completeness_or_external_targets(change):
    with pytest.raises(ValueError):
        source_year_checks(
            source(), {"year_checks": {"2023": evidence(**change)}}, {"Meeting", "Joint"}
        )


def test_joint_editions_link_to_an_existing_source_without_adding_papers():
    row = source()
    checks = source_year_checks(
        row,
        {"year_checks": {"2026": evidence("joint_edition", canonical_venue="Joint")}},
        {"Meeting", "Joint"},
    )
    assert checks["2026"]["canonical_venue"] == "Joint"
    assert not row["primary_years"].get("2026")


def test_evidence_outside_the_agreed_year_range_is_rejected():
    with pytest.raises(ValueError):
        source_year_checks(source(), {"year_checks": {"2027": evidence()}}, {"Meeting"})
