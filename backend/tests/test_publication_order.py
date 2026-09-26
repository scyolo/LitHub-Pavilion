"""Publication ordering uses upstream dates, never ingestion timestamps."""
import pytest

from app.models import Paper


@pytest.mark.parametrize("date,year,expected", [
    ("2026-03-02", 2024, "2026-03-02"), ("2024-02-29", 2023, "2024-02-29"),
    ("2025-02-29", 2025, "2025-00-00"), ("2026-04-31", 2026, "2026-00-00"),
    (None, 2026, "2026-00-00"), ("", 2025, "2025-00-00"),
    ("2026-03", 2024, "2024-00-00"), ("2026-01-01T00:00:00Z", 2025, "2025-00-00"),
    (" 2026-03-01", 2025, "2025-00-00"), (None, None, ""),
])
def test_publication_sort_key(date, year, expected):
    from app.publication import publication_sort_key
    assert publication_sort_key({"publication_date": date, "year": year}) == expected


def test_default_api_order_and_search_are_stable_before_pagination(client, db, api_catalog):
    dates = {11: "2026-04-02", 23: "2026-04-02", 35: None, 47: "2025-12-31", 59: "2025-02-29", 71: "2026-01-01", 83: "2024-12-31"}
    for pid, date in dates.items():
        paper = db.get(Paper, pid)
        paper.publication_date = date
        if pid in (35, 59):
            paper.year = 2026
    db.commit()
    expected = [23, 11, 71, 59, 35, 47, 83]
    result = client.get("/api/papers", params={"size": 100})
    assert result.status_code == 200
    assert [p["id"] for p in result.json()["items"]] == expected
    ids = []
    for page in range(1, 5):
        response = client.get("/api/search", params={"q": "radar", "sort": "publication_desc", "page": page, "size": 2})
        assert response.status_code == 200
        ids.extend(p["id"] for p in response.json()["items"])
    assert ids == expected


def test_publication_function_survives_connection_recreation(engine):
    for _ in range(2):
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT publication_sort_key('2024-02-29', 2026)").scalar() == "2024-02-29"
        engine.dispose()
