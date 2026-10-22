"""Keep observed source/year counts separate from evidence about empty years."""

from collections import Counter
from datetime import date
from urllib.parse import urlsplit

YEARS = (2023, 2024, 2025, 2026)
ZERO_YEAR_STATUSES = {
    "unverified",
    "not_scheduled",
    "joint_edition",
    "publication_pending",
    "no_proceedings",
    "edition_unverified",
    "retrieval_failed",
}


def _verified_check(value, abbr, configured):
    if not isinstance(value, dict) or value.get("status") not in ZERO_YEAR_STATUSES:
        raise ValueError(f"Invalid source/year evidence for {abbr}")
    note = value.get("note")
    if not isinstance(note, str) or not note.strip() or len(note) > 1000:
        raise ValueError(f"Missing bounded source/year explanation for {abbr}")
    result = {"status": value["status"], "note": note.strip()}
    if value["status"] != "unverified" or "evidence_url" in value:
        url = value.get("evidence_url")
        if not isinstance(url, str):
            raise ValueError(f"Missing source/year evidence URL for {abbr}")
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError(f"Unsafe source/year evidence URL for {abbr}")
        checked = value.get("checked_at")
        try:
            if not isinstance(checked, str) or date.fromisoformat(checked).isoformat() != checked:
                raise ValueError
        except (TypeError, ValueError) as error:
            raise ValueError(f"Missing source/year evidence date for {abbr}") from error
        result.update(evidence_url=url, checked_at=checked)
    if "canonical_venue" in value:
        target = value["canonical_venue"]
        if value["status"] != "joint_edition" or target == abbr or target not in configured:
            raise ValueError(f"Unconfigured joint-edition target for {abbr}")
        result["canonical_venue"] = target
    return result


def source_year_checks(source, notes, configured):
    """An annotation never erases a zero or overrides a newly populated year."""
    checks = notes.get("year_checks", {})
    if not isinstance(checks, dict) or any(str(year) not in {str(y) for y in YEARS} for year in checks):
        raise ValueError(f"Invalid source/year evidence range for {source['abbr']}")
    result = {}
    for year in YEARS:
        key = str(year)
        if source["primary_years"].get(key, 0) or source["associated_years"].get(key, 0):
            continue
        check = checks.get(key)
        result[key] = (
            _verified_check(check, source["abbr"], configured)
            if check is not None
            else {
                "status": "unverified",
                "note": "尚未取得足以解释本年度零记录的出版证据，仍需核对官网目录与采集结果。",
            }
        )
    return result


def zero_year_summary(sources):
    counts = Counter(
        check["status"]
        for source in sources
        for check in source["year_checks"].values()
    )
    return {
        "zero_source_year_units": sum(counts.values()),
        "zero_year_status_counts": dict(sorted(counts.items())),
    }
