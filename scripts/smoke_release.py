"""Smoke-test the isolated release deployment at the fixed loopback port 8180.

This local developer command is not a server route. It never accepts remote URLs,
resolves user-selected hosts, or follows redirects.
"""
import csv
import http.client
import json
from pathlib import Path


def get(path):
    connection = http.client.HTTPConnection("127.0.0.1", 8180, timeout=30)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def main():
    seeds = Path(__file__).resolve().parents[1] / "seeds"
    with (seeds / "venues.csv").open(encoding="utf-8-sig", newline="") as source:
        expected_venues = {row["abbr"] for row in csv.DictReader(source)}
    status, headers, body = get("/")
    assert status == 200
    assert "LitHub Pavilion" in body.decode("utf-8")
    assert headers.get("X-Content-Type-Options") == "nosniff"
    status, _, body = get("/api/health")
    assert status == 200 and json.loads(body)["db"] == "ok"
    status, _, body = get("/api/stats/dashboard")
    assert status == 200
    dashboard = json.loads(body)
    assert dashboard["total"] == 0
    assert dashboard["configured_venues"] == len(expected_venues)
    assert len(dashboard["directions"]) == 9
    status, _, body = get("/api/crawl/status")
    assert status == 200
    crawl = json.loads(body)
    assert crawl["mode"] == "links" and "pdf_download_enabled" not in crawl
    status, _, body = get("/api/papers/1/pdf")
    assert status == 404
    status, _, body = get("/api/search?q=speculative")
    assert status == 200 and json.loads(body)["total"] == 0
    status, _, body = get("/api/venues")
    assert status == 200 and {venue["abbr"] for venue in json.loads(body)["items"]} == expected_venues
    status, _, body = get("/api/papers?level=C")
    assert status == 400 and json.loads(body)["error"]["code"] == "INVALID_PARAM"
    print(f"PASS: page, security headers, empty SQLite/FTS5, {len(expected_venues)} A/B sources, nine topics, link-only API")


if __name__ == "__main__":
    main()
