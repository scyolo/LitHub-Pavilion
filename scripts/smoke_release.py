"""Smoke-test the isolated release deployment at the fixed loopback port 8180.

This local developer command is not a server route. It never accepts remote URLs,
resolves user-selected hosts, or follows redirects.
"""
import http.client
import json


def get(path):
    connection = http.client.HTTPConnection("127.0.0.1", 8180, timeout=30)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def main():
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
    assert dashboard["configured_venues"] == 28
    assert len(dashboard["directions"]) == 9
    status, _, body = get("/api/crawl/status")
    assert status == 200 and json.loads(body)["mode"] == "links"
    status, _, body = get("/api/search?q=speculative")
    assert status == 200 and json.loads(body)["total"] == 0
    status, _, body = get("/api/venues")
    assert status == 200 and len(json.loads(body)["items"]) == 28
    status, _, body = get("/api/papers?level=C")
    assert status == 400 and json.loads(body)["error"]["code"] == "INVALID_PARAM"
    print("PASS: page, security headers, empty SQLite/FTS5, 28 A/B sources, nine topics, link-only API")


if __name__ == "__main__":
    main()
