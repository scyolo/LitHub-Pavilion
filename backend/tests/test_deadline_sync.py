from datetime import datetime, timezone

from scripts.sync_deadlines import build_feed, deadline_utc


def venue(abbr="SoCC", stream="conf/cloud", level="B"):
    return {"abbr": abbr, "name": "ACM Symposium on Cloud Computing", "dblp_stream": stream,
            "type": "conf", "ccf_level": level, "ccf_area": "计算机体系结构/并行与分布计算/存储系统"}


def conference(title="SoCC", **kwargs):
    return {"title": title, "dblp": "cloud", "confs": [{"year": 2027, "id": "socc27",
            "link": "https://acmsocc.org/2027/", "timezone": "AoE", "timeline": [
                {"abstract_deadline": "2026-09-30 23:59:59", "deadline": "2026-10-07 23:59:59", "comment": "round 1"},
                {"deadline": "TBD", "comment": "round 2"}], **kwargs}]}


def test_aoe_is_next_day_utc_not_browser_local_time():
    assert deadline_utc("2026-09-30 23:59:59", "AoE") == "2026-10-01T11:59:59Z"
    assert deadline_utc("2026-10-01 23:00:00", "UTC+8") == "2026-10-01T15:00:00Z"
    assert deadline_utc("2026-10-01 17:30:00", "UTC+05:30") == "2026-10-01T12:00:00Z"


def test_unknown_deadlines_and_zones_are_not_guessed():
    assert deadline_utc("TBD", "AoE") is None
    assert deadline_utc("2026-10-07", "AoE") is None
    assert deadline_utc("2026-10-07 23:59:59", "UNKNOWN") is None
    assert deadline_utc("2026-02-30 23:59:59", "AoE") is None


def test_pacific_timezone_uses_dst_at_the_deadline_not_a_fixed_offset():
    assert deadline_utc("2026-07-01 23:59:59", "PT") == "2026-07-02T06:59:59Z"
    assert deadline_utc("2026-12-01 23:59:59", "PT") == "2026-12-02T07:59:59Z"


def test_rounds_abstracts_and_provenance_survive_and_ids_are_stable():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    sources = [("conference/DS/socc.yml", [conference()])]
    feed = build_feed([venue()], sources, now, "a" * 64)
    assert len(feed["events"]) == 2
    first, second = feed["events"]
    assert first["deadline_utc"] == "2026-10-08T11:59:59Z"
    assert first["abstract_deadline_utc"] == "2026-10-01T11:59:59Z"
    assert first["source_url"].endswith("conference/DS/socc.yml")
    assert second["deadline_utc"] is None
    assert feed["coverage"]["matched_conferences"] == 1
    assert [e["id"] for e in feed["events"]] == [e["id"] for e in build_feed([venue()], sources, now, "b" * 64)["events"]]


def test_shared_dblp_slug_must_not_confuse_ieee_cloud_with_acm_socc():
    feed = build_feed([venue()], [("conference/DS/cloud.yml", [conference("Cloud")])],
                      datetime(2026, 10, 1, tzinfo=timezone.utc), "a" * 64)
    assert feed["events"] == []
    assert feed["coverage"]["missing_venues"] == ["SoCC"]


def test_latest_ccf_catalog_wins_over_upstream_rank_and_unsafe_links_are_removed():
    source = conference(link="javascript:alert(1)")
    source["rank"] = {"ccf": "C"}
    feed = build_feed([venue(level="A")], [("conference/DS/socc.yml", [source])],
                      datetime(2026, 10, 1, tzinfo=timezone.utc), "a" * 64)
    assert all(e["level"] == "A" and e["link"] is None for e in feed["events"])
