import csv

import pytest

from scripts.build_industry_data import (
    DEFAULT_ORGS,
    DEFAULT_REPORTS,
    ORG_COLUMNS,
    REPORT_COLUMNS,
    build_feed,
    load_orgs,
    load_reports,
)


def seeds():
    orgs = load_orgs(DEFAULT_ORGS)
    return orgs, load_reports(DEFAULT_REPORTS, {org["code"] for org in orgs})


def write_csv(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def raw_report(**overrides):
    row = {
        "id": "example-report", "org": "deepseek", "title": "Example Technical Report",
        "kind": "tech_report", "year": "2025", "published": "2025-01-02",
        "url": "https://arxiv.org/abs/2501.00001", "arxiv_id": "2501.00001",
        "summary": "示例报告摘要，用于校验目录数据。", "tags": "LLM;开源",
    }
    row.update(overrides)
    return row


def test_seed_catalog_has_expected_shape_and_unique_identities():
    orgs, reports = seeds()
    assert len(orgs) == 24
    assert len(reports) == 112
    assert sum(report["org"] == "deepseek" for report in reports) == 26
    assert len({report["id"] for report in reports}) == len(reports)
    assert all(report["url"].startswith("https://") for report in reports)
    assert all((report["arxiv_id"] is not None) == ("arxiv.org" in report["url"]) for report in reports)
    assert all(2000 <= report["year"] <= 2100 for report in reports)


def test_feed_stats_ordering_and_org_counts():
    orgs, reports = seeds()
    feed = build_feed(orgs, reports, generated_at="2026-10-28T00:00:00Z")
    assert feed["generated_at"] == "2026-10-28T00:00:00Z"
    assert feed["stats"]["reports"] == 112
    assert feed["stats"]["orgs"] == 24
    assert feed["stats"]["latest"] == "2026-10-16"
    assert feed["orgs"][0]["code"] == "deepseek"
    assert feed["orgs"][0]["count"] == 26
    assert feed["reports"][0]["id"] == "deepseek-deepinfer"
    published = [report["published"] for report in feed["reports"]]
    assert published == sorted(published, reverse=True)
    assert sum(org["count"] for org in feed["orgs"]) == len(feed["reports"])


def test_report_validation_rejects_broken_identity_and_links(tmp_path):
    path = tmp_path / "reports.csv"
    write_csv(path, REPORT_COLUMNS, [raw_report()])
    assert load_reports(path, {"deepseek"})[0]["arxiv_id"] == "2501.00001"

    cases = [
        {"id": "Bad Id"},
        {"arxiv_id": "2501.99999"},
        {"url": "http://arxiv.org/abs/2501.00001"},
        {"url": "https://127.0.0.1/report.pdf", "arxiv_id": ""},
        {"published": "2024-01-02"},
        {"kind": "whitepaper"},
        {"summary": "short"},
        {"tags": "LLM;LLM"},
    ]
    for overrides in cases:
        write_csv(path, REPORT_COLUMNS, [raw_report(**overrides)])
        with pytest.raises(ValueError):
            load_reports(path, {"deepseek"})


def test_report_validation_rejects_unknown_org_duplicate_titles_and_missing_columns(tmp_path):
    path = tmp_path / "reports.csv"
    write_csv(path, REPORT_COLUMNS, [raw_report(org="unknown")])
    with pytest.raises(ValueError):
        load_reports(path, {"deepseek"})
    rows = [raw_report(), raw_report(id="another-report")]
    write_csv(path, REPORT_COLUMNS, rows)
    with pytest.raises(ValueError):
        load_reports(path, {"deepseek"})
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write("id,org,title\none,deepseek,Example\n")
    with pytest.raises(ValueError):
        load_reports(path, {"deepseek"})


def test_org_validation_and_feed_require_reports_for_every_org(tmp_path):
    path = tmp_path / "orgs.csv"
    write_csv(path, ORG_COLUMNS, [
        {"code": "deepseek", "name": "深度求索", "name_en": "DeepSeek", "country": "中国", "note": "示例机构"},
        {"code": "empty", "name": "空机构", "name_en": "Empty", "country": "中国", "note": "没有报告"},
    ])
    orgs = load_orgs(path)
    assert [org["code"] for org in orgs] == ["deepseek", "empty"]
    reports = [{
        "id": "example-report", "org": "deepseek", "title": "Example Technical Report",
        "kind": "tech_report", "year": 2025, "published": "2025-01-02",
        "url": "https://arxiv.org/abs/2501.00001", "arxiv_id": "2501.00001",
        "summary": "示例报告摘要，用于校验目录数据。", "tags": ["LLM"],
    }]
    with pytest.raises(ValueError):
        build_feed(orgs, reports, generated_at="2026-10-28T00:00:00Z")


def test_generated_at_requires_an_explicit_timezone():
    orgs, reports = seeds()
    with pytest.raises(ValueError):
        build_feed(orgs, reports, generated_at="2026-10-28T00:00:00")
