"""API 行为测试：列表筛选、详情、错误信封、POST 201+Location、检索。"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import event

from app.config import settings
from app.models import CrawlLog


def test_list_papers_with_filters(client, sample_paper):
    resp = client.get("/api/papers", params={"direction": "specdec", "level": "A", "year": 2024})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 0
    if body["total"]:
        item = body["items"][0]
        for key in ("id", "title", "venue", "level", "year", "directions", "citation_count", "pdf_status", "doi"):
            assert key in item


def test_list_invalid_params_400_envelope(client):
    resp = client.get("/api/papers", params={"size": 500})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_PARAM"
    resp = client.get("/api/papers", params={"level": "C"})
    assert resp.status_code == 400


def test_detail_not_found_envelope(client):
    resp = client.get("/api/papers/99999")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PAPER_NOT_FOUND"


def test_detail_contains_all_fields(client, sample_paper):
    resp = client.get(f"/api/papers/{sample_paper.id}")
    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "title", "abstract", "authors", "venue", "directions", "pdf_status",
        "pdf_url", "oa_url", "official_url", "venue_confirmed", "publication_date",
    ):
        assert key in body
    assert body["venue"]["abbr"] == "NeurIPS"


def test_create_paper_returns_201_with_location(client, sample_venue):
    resp = client.post(
        "/api/papers",
        json={
            "title": "Manually Added Paper",
            "venue_abbr": "NeurIPS",
            "year": 2025,
            "doi": "10.5555/manual.001",
        },
    )
    assert resp.status_code == 201
    assert resp.headers["location"] == f"/api/papers/{resp.json()['id']}"
    # 重复 dblp_key/doi → 409
    resp2 = client.post(
        "/api/papers",
        json={
            "title": "Manually Added Paper",
            "venue_abbr": "NeurIPS",
            "year": 2025,
            "doi": "10.5555/manual.001",
        },
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "DUPLICATE"


def test_search_requires_query(client):
    resp = client.get("/api/search", params={"q": "  "})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "EMPTY_QUERY"


def test_search_matches_title(client, sample_paper):
    resp = client.get("/api/search", params={"q": "speculative decoding"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    ids = [item["id"] for item in body["items"]]
    assert sample_paper.id in ids
    assert "score" in body["items"][0]


def test_directions_and_venues_and_stats(client, sample_venue, sample_direction, sample_paper):
    resp = client.get("/api/directions")
    assert resp.status_code == 200
    assert any(d["code"] == "specdec" for d in resp.json()["items"])

    resp = client.get("/api/venues", params={"level": "A"})
    assert resp.status_code == 200
    assert any(v["abbr"] == "NeurIPS" for v in resp.json()["items"])

    resp = client.get("/api/stats/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert body["by_level"]["A"] >= 1
    assert "last_crawl_at" in body


def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["db"] == "ok"


@pytest.mark.parametrize("filters,expected", [
    ({}, {11, 23, 35, 47, 59, 71, 83}),
    ({"level": "A"}, {11, 35, 59, 83}),
    ({"level": "B"}, {23, 47, 71}),
    ({"type": "journal"}, {35, 47}),
    ({"type": "conf"}, {11, 23, 59, 71, 83}),
    ({"direction": "specdec,llm"}, {11, 23, 35, 59, 71, 83}),
    ({"direction": " specdec, llm,specdec "}, {11, 23, 35, 59, 71, 83}),
    ({"direction": "unknown"}, set()),
    ({"venue": "BC"}, {23, 71}),
    ({"venue": "HIDDEN_C"}, set()),
    ({"year": "2024"}, {11, 71}),
    ({"access": "oa"}, {11, 23, 59, 83}),
    ({"access": "official"}, {35, 47, 71}),
    ({"level": "A", "type": "conf", "direction": "specdec,llm", "venue": "AC", "year": "2024", "access": "oa"}, {11}),
    ({"level": "B", "type": "conf", "direction": "llm", "access": "official"}, {71}),
    ({"level": "A", "type": "journal", "access": "oa"}, set()),
])
def test_list_search_dashboard_share_filtered_scope(client, api_catalog, filters, expected):
    listing = client.get("/api/papers", params={**filters, "size": 100})
    search = client.get("/api/search", params={**filters, "q": "radar", "size": 100})
    dashboard = client.get("/api/stats/dashboard", params=filters)
    assert listing.status_code == search.status_code == dashboard.status_code == 200
    assert {p["id"] for p in listing.json()["items"]} == expected
    assert {p["id"] for p in search.json()["items"]} == expected
    data = dashboard.json()
    assert listing.json()["total"] == search.json()["total"] == data["total"] == len(expected)
    assert data["with_oa_link"] == len(expected & {11, 23, 59, 83})
    assert data["with_abstract"] == len(expected & {11, 59, 71})
    assert data["confirmed_count"] == len(expected & {11, 35, 71})
    assert data["recent_count"] == len(expected & {11, 35, 71, 83})
    assert data["by_level"] == {"A": len(expected & {11, 35, 59, 83}), "B": len(expected & {23, 47, 71})}
    assert data["by_type"] == {"conf": len(expected & {11, 23, 59, 71, 83}), "journal": len(expected & {35, 47})}
    assert sum(row["total"] for row in data["annual"]) == len(expected)
    assert sum(v["paper_count"] for v in data["venues"]) == len(expected)
    configured = [v for v in api_catalog["venues"] if (
        (not filters.get("level") or v.ccf_level == filters["level"])
        and (not filters.get("type") or v.type == filters["type"])
    )]
    assert data["configured_venues"] == len(configured)
    assert data["venues_with_papers"] == len({p.venue_id for p in api_catalog["papers"] if p.id in expected})
    for row in data["annual"]:
        year_ids = {p.id for p in api_catalog["papers"] if p.year == row["year"]} & expected
        assert row == {"year": row["year"], "A": len(year_ids & {11, 35, 59, 83}), "B": len(year_ids & {23, 47, 71}), "total": len(year_ids)}
    memberships = {"specdec": {11, 23, 83}, "llm": {11, 35, 59, 71}, "agent": {47, 83}, "unused": set()}
    for direction in data["directions"]:
        assert direction["paper_count"] == len(expected & memberships[direction["code"]])
    for venue in data["venues"]:
        assert venue["level"] in {"A", "B"}
        assert venue["type"] in {"conf", "journal"}
        assert venue["paper_count"] == len({p.id for p in api_catalog["papers"] if p.venue_id == venue["id"]} & expected)
        assert sum(year["count"] for year in venue["years"]) == venue["paper_count"]


@pytest.mark.parametrize("params", [
    {"level": "C"}, {"level": ""}, {"type": "workshop"}, {"type": ""},
    {"access": "downloaded"}, {"access": ""}, {"year": "24"},
    {"year": "02024"}, {"year": "2024.0"}, {"direction": ",llm"},
])
def test_filter_validation_is_consistently_400(client, params):
    for path in ("/api/papers", "/api/search", "/api/stats/dashboard"):
        response = client.get(path, params={**params, **({"q": "radar"} if path == "/api/search" else {})})
        assert response.status_code == 400, (path, response.text)
        assert response.json()["error"]["code"] == "INVALID_PARAM"


@pytest.mark.parametrize("q", ["", " ", "中文查询", "radar 中文", "x" * 301, " ".join(["radar"] * 25), "!!!"])
def test_search_rejects_empty_unsupported_and_excessive_queries(client, q):
    response = client.get("/api/search", params={"q": q})
    assert response.status_code == 400
    assert "error" in response.json()


@pytest.mark.parametrize("q", ["x" * 300, " ".join(["radar"] * 24), 'radar" OR "model'])
def test_search_accepts_query_boundaries_without_fts_injection(client, q):
    assert client.get("/api/search", params={"q": q}).status_code == 200


@pytest.mark.parametrize("params", [{"sort": "rank"}, {"pdf_status": "bad"}, {"page": 0}, {"size": 101}])
def test_list_and_search_reject_invalid_legacy_parameters(client, params):
    for path in ("/api/papers", "/api/search"):
        assert client.get(path, params={**params, "q": "radar"}).status_code == 400


def test_list_search_keep_pdf_status_filter(client, api_catalog):
    for path in ("/api/papers", "/api/search"):
        response = client.get(path, params={"q": "radar", "pdf_status": "downloaded", "access": "official"})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["id"] == 71


@pytest.mark.parametrize("sort,expected", [
    ("relevance", [83, 71, 59, 47, 35, 23, 11]),
    ("year_desc", [59, 35, 47, 71, 11, 83, 23]),
    ("citation_desc", [23, 59, 11, 47, 83, 71, 35]),
    ("created_desc", [59, 11, 71, 35, 83, 23, 47]),
])
def test_search_sort_and_pagination_have_stable_id_tiebreak(client, api_catalog, db, sort, expected):
    for paper in api_catalog["papers"]:
        paper.abstract = None
    db.commit()
    ids = []
    for page in range(1, 5):
        response = client.get("/api/search", params={"q": "radar", "sort": sort, "page": page, "size": 2})
        assert response.status_code == 200
        assert response.json()["total"] == 7
        ids.extend(item["id"] for item in response.json()["items"])
    assert ids == expected
    if sort == "relevance":
        default = client.get("/api/search", params={"q": "radar", "size": 100}).json()
        assert [item["id"] for item in default["items"]] == expected


def test_dashboard_zero_data_and_year_semantics(client):
    before = datetime.now(timezone.utc)
    response = client.get("/api/stats/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert before <= datetime.fromisoformat(data["generated_at"]) <= datetime.now(timezone.utc)
    assert data["total"] == data["with_oa_link"] == data["with_abstract"] == 0
    assert data["recent_count"] == data["confirmed_count"] == 0
    assert data["by_level"] == {"A": 0, "B": 0}
    assert data["by_type"] == {"conf": 0, "journal": 0}
    assert data["annual"] == [{"year": year, "A": 0, "B": 0, "total": 0} for year in range(2023, before.year + 1)]
    assert data["directions"] == data["venues"] == []
    assert data["configured_venues"] == data["venues_with_papers"] == 0
    assert data["last_crawl"] is None
    description = client.get("/openapi.json").json()["paths"]["/api/stats/dashboard"]["get"]["description"]
    assert "Paper.year" in description and "created_at" in description


def test_dashboard_keeps_zero_venues_and_overlapping_directions(client, api_catalog):
    data = client.get("/api/stats/dashboard").json()
    assert data["total"] == 7
    assert sum(d["paper_count"] for d in data["directions"]) == 9
    empty = next(v for v in data["venues"] if v["abbr"] == "EMPTY")
    assert empty["id"] == 509
    assert empty["paper_count"] == 0
    assert {"name", "type", "level", "ccf_area", "active", "years"} <= empty.keys()
    data = client.get("/api/stats/dashboard", params={"level": "B", "type": "journal", "direction": "unknown"}).json()
    assert data["total"] == data["venues_with_papers"] == 0
    assert data["configured_venues"] == 2
    assert {v["abbr"] for v in data["venues"]} == {"BJ", "EMPTY"}
    assert all(row["total"] == 0 for row in data["annual"])


def test_dashboard_recent_count_uses_created_at_not_publication_date(client, api_catalog):
    # id=23 今天发表但九天前入库，id=59 的未来入库时间也不应算进最近七天。
    data = client.get("/api/stats/dashboard").json()
    assert data["recent_count"] == 4
    assert next(row for row in data["annual"] if row["year"] == 2023)["total"] == 2
    assert next(row for row in data["annual"] if row["year"] == 2024)["total"] == 2


def test_dashboard_last_crawl_exposes_failed_and_partial_child_units(client, api_catalog, db):
    db.add_all([
        CrawlLog(run_id="old", task_type="weekly", status="failed", started_at="2025-01-01T00:00:00+00:00"),
        CrawlLog(run_id="latest", task_type="backfill", status="success", papers_new=7, papers_updated=2,
                 started_at="2025-02-01T00:00:00+00:00", finished_at="2025-02-01T02:00:00+00:00", error="Probe note"),
        CrawlLog(run_id="latest", task_type="backfill", venue_id=101, status="failed", started_at="2025-02-01T00:10:00+00:00", error="Timeout"),
        CrawlLog(run_id="latest", task_type="backfill", venue_id=203, status="partial", started_at="2025-02-01T00:20:00+00:00"),
        CrawlLog(run_id="latest", task_type="backfill", venue_id=305, status="success", started_at="2025-02-01T00:30:00+00:00"),
        CrawlLog(run_id="maintenance", task_type="monthly", status="success", started_at="2025-03-01T00:00:00+00:00"),
    ])
    db.commit()
    data = client.get("/api/stats/dashboard", params={"venue": "EMPTY"}).json()["last_crawl"]
    assert data == {
        "run_id": "latest", "status": "partial", "started_at": "2025-02-01T00:00:00+00:00",
        "finished_at": "2025-02-01T02:00:00+00:00", "papers_new": 7, "papers_updated": 2,
        "failed_units": 2, "error": "Probe note",
    }


def test_cards_share_new_fields_and_preserve_legacy_fields(client, api_catalog):
    list_card = next(p for p in client.get("/api/papers").json()["items"] if p["id"] == 11)
    search_card = next(p for p in client.get("/api/search", params={"q": "radar"}).json()["items"] if p["id"] == 11)
    assert "score" in search_card
    search_card.pop("score")
    assert list_card == search_card
    legacy = {"id", "title", "venue", "level", "year", "directions", "first_author", "authors_count", "citation_count", "pdf_status", "pdf_source", "doi"}
    assert legacy <= list_card.keys()
    assert list_card["venue"] == "AC"
    assert list_card["venue_name"] == "A Conference"
    assert list_card["venue_type"] == "conf"
    assert list_card["abstract_preview"] == "x" * 360
    assert list_card["authors_preview"] == ["First", "Second", "Third"]
    assert list_card["first_author"] == "First" and list_card["authors_count"] == 4
    assert list_card["publication_date"] is None
    assert list_card["year"] == 2024  # dblp_key 末尾的 1999 不改变 DB 归属年。
    assert list_card["created_at"] == api_catalog["papers"][0].created_at
    assert list_card["venue_confirmed"] in (True, 1)
    assert list_card["official_url"] == "https://doi.org/10.5555/radar.11"
    assert list_card["oa_url"] == "https://oa.example.org/11"
    detail = client.get("/api/papers/11").json()
    assert detail["official_url"] == list_card["official_url"]
    assert detail["oa_url"] == list_card["oa_url"]
    assert detail["venue"]["abbr"] == "AC"
    assert detail["publication_date"] is None


@pytest.mark.parametrize("enabled,mode", [(False, "links"), (True, "downloads")])
def test_detail_and_status_report_configured_mode(client, sample_paper, monkeypatch, enabled, mode):
    monkeypatch.setattr(settings, "pdf_download_enabled", enabled)
    assert client.get(f"/api/papers/{sample_paper.id}").json()["mode"] == mode
    status = client.get("/api/crawl/status").json()
    assert status["mode"] == mode
    assert status["pdf_download_enabled"] is enabled
    assert status["schedule"] is None
    assert {"running", "run_id", "current", "progress", "last_error"} <= status.keys()


def test_crawl_schedule_reads_registered_jobs_without_mutation(client, monkeypatch):
    now = datetime.now(timezone.utc)
    peak = now + timedelta(days=1)
    regular = now + timedelta(days=4)
    links = now + timedelta(days=5)
    scheduler = Mock()
    scheduler.timezone = "Asia/Shanghai"
    scheduler.get_jobs.return_value = [
        SimpleNamespace(id="weekly_crawl", next_run_time=regular, kwargs={"api_key": "private"}),
        SimpleNamespace(id="weekly_crawl_peak", next_run_time=peak),
        SimpleNamespace(id="links_backfill", next_run_time=links),
        SimpleNamespace(id="monthly_metrics", next_run_time=now),
    ]
    monkeypatch.setattr(client.app.state, "scheduler", scheduler)
    data = client.get("/api/crawl/status").json()
    assert data["schedule"] == {"timezone": "Asia/Shanghai", "next_crawl_at": peak.isoformat(), "next_links_at": links.isoformat()}
    assert "private" not in str(data) and "api_key" not in str(data)
    scheduler.get_jobs.assert_called_once_with()
    scheduler.add_job.assert_not_called()
    scheduler.modify_job.assert_not_called()
    scheduler.reschedule_job.assert_not_called()


def test_crawl_schedule_handles_pending_paused_and_missing_jobs(client, monkeypatch):
    scheduler = Mock()
    scheduler.timezone = "UTC"
    scheduler.get_jobs.return_value = [SimpleNamespace(id="weekly_crawl"), SimpleNamespace(id="weekly_crawl_peak", next_run_time=None)]
    monkeypatch.setattr(client.app.state, "scheduler", scheduler)
    assert client.get("/api/crawl/status").json()["schedule"] == {"timezone": "UTC", "next_crawl_at": None, "next_links_at": None}


def test_scope_is_consistent_for_legacy_stats_taxonomies_and_detail(client, api_catalog):
    stats = client.get("/api/stats/overview").json()
    assert stats["total"] == 7
    assert stats["with_oa_link"] == 4
    assert stats["by_direction"]["specdec"] == 3
    assert stats["by_level"] == {"A": 4, "B": 3}
    assert stats["pdf_archived"] == 1
    assert {v["abbr"] for v in client.get("/api/venues").json()["items"]} == {"AC", "BC", "AJ", "BJ", "EMPTY"}
    directions = client.get("/api/directions").json()["items"]
    assert next(d for d in directions if d["code"] == "specdec")["paper_count"] == 3
    for pid in api_catalog["hidden_ids"]:
        assert client.get(f"/api/papers/{pid}").status_code == 404


@pytest.mark.parametrize("path,params,max_queries", [
    ("/api/papers", {"size": 100}, 4),
    ("/api/search", {"q": "radar", "size": 100}, 5),
    ("/api/stats/dashboard", {}, 9),
])
def test_api_reads_are_batched_and_dashboard_uses_sql_aggregates(client, api_catalog, engine, path, params, max_queries):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(path, params=params)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert len(statements) <= max_queries
    if path.endswith("dashboard"):
        paper_queries = [sql.lower() for sql in statements if "papers.id" in sql.lower()]
        assert paper_queries and all("count(" in sql or "sum(" in sql for sql in paper_queries)
        assert all("papers.abstract as" not in sql and "papers.title as" not in sql for sql in paper_queries)


@pytest.fixture()
def link_caches():
    from app.api.serializers import _cached_oa_link, _safe_host

    caches = (_cached_oa_link, _safe_host)
    for cached in caches:
        cached.cache_clear()
    try:
        yield caches
    finally:
        for cached in caches:
            cached.cache_clear()


def test_oa_cache_is_shared_by_sql_aggregates_and_cards(client, db, sample_paper, monkeypatch, link_caches):
    from app.api import serializers

    url = "https://cache.example.org/shared.pdf"
    sample_paper.oa_url = url
    db.commit()
    checked = Mock(wraps=serializers.safe_http_url)
    monkeypatch.setattr(serializers, "safe_http_url", checked)
    dashboard = client.get("/api/stats/dashboard", params={"access": "oa"}).json()
    assert dashboard["total"] == dashboard["with_oa_link"] == 1
    for path in ("/api/papers", "/api/search"):
        response = client.get(path, params={"access": "oa", "q": "speculative"})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["oa_url"] == url
    assert client.get(f"/api/papers/{sample_paper.id}").json()["oa_url"] == url
    assert sum(call.args == (url,) for call in checked.call_args_list) == 1
    cache, _ = link_caches
    assert cache.cache_info().misses == 1
    assert cache.cache_info().hits > 1


def test_cached_oa_values_do_not_hide_database_updates(client, db, sample_paper, link_caches):
    for oa_url, arxiv_id, expected in [
        ("https://cache.example.org/paper", None, "https://cache.example.org/paper"),
        ("javascript:alert(1)", None, None),
        ("javascript:alert(1)", "2401.12345", "https://arxiv.org/abs/2401.12345"),
        ("javascript:alert(1)", "2401.54321", "https://arxiv.org/abs/2401.54321"),
        ("javascript:alert(1)", "invalid", None),
        ("https://other.example.org/paper", "invalid", "https://other.example.org/paper"),
    ]:
        sample_paper.oa_url = oa_url
        sample_paper.arxiv_id = arxiv_id
        db.commit()
        assert client.get("/api/papers").json()["items"][0]["oa_url"] == expected
        assert client.get(f"/api/papers/{sample_paper.id}").json()["oa_url"] == expected
        expected_count = int(expected is not None)
        assert client.get("/api/stats/dashboard").json()["with_oa_link"] == expected_count
        assert client.get("/api/stats/dashboard", params={"access": "oa"}).json()["total"] == expected_count
        assert client.get("/api/search", params={"q": "speculative", "access": "oa"}).json()["total"] == expected_count
        assert client.get("/api/papers", params={"access": "official"}).json()["total"] == 1 - expected_count


def test_host_cache_reuses_validation_without_trusting_whole_urls(monkeypatch, link_caches):
    from app.api import serializers

    checked = Mock(wraps=serializers.ipaddress.ip_address)
    monkeypatch.setattr(serializers.ipaddress, "ip_address", checked)
    for url in ("https://cache.example.org/one", "http://cache.example.org:8080/two"):
        assert serializers.safe_http_url(url) == url
    assert checked.call_count == 1
    for unsafe in (
        "https://user:password@cache.example.org/one", "https://cache.example.org:bad/one",
        "https://cache.example.org/a\nb", "https://cache.example.org/%0d%0aHeader",
    ):
        assert serializers.safe_http_url(unsafe) is None
    _, cached_host = link_caches
    assert cached_host.cache_info().misses == 1
    assert cached_host.cache_info().hits == 1


def test_link_caches_are_bounded_and_evicted_values_are_revalidated(link_caches):
    from app.api.serializers import oa_link, safe_http_url

    cache, host_cache = link_caches
    assert cache.cache_info().maxsize == 32768
    for i in range(32769):
        assert oa_link(f"javascript:cache-test-{i}", None) is None
    assert cache.cache_info().currsize == 32768
    assert oa_link("javascript:cache-test-0", None) is None
    assert cache.cache_info().misses == 32770
    assert host_cache.cache_info().maxsize == 1024
    for i in range(1025):
        url = f"https://host{i}.example.org/paper"
        assert safe_http_url(url) == url
    assert host_cache.cache_info().currsize == 1024
    assert safe_http_url("https://host0.example.org/paper") == "https://host0.example.org/paper"
    assert host_cache.cache_info().misses == 1026


def test_oversized_cache_keys_are_not_retained_or_rejected(link_caches):
    from app.api.serializers import oa_link, safe_http_url

    cache, host_cache = link_caches
    long_url = "https://cache.example.org/" + "a" * 4096
    assert oa_link(long_url, None) == long_url
    assert oa_link(None, "x" * 4096) is None
    assert cache.cache_info().currsize == 0
    host_size = host_cache.cache_info().currsize
    assert safe_http_url("https://" + "a" * 4096 + ".example.org/paper") is None
    assert host_cache.cache_info().currsize == host_size
