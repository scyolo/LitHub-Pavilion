import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def classic_rows():
    with (ROOT / "seeds" / "direction_classics.csv").open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def test_classic_ids_and_directions_are_unique_and_registered(seed_direction_codes):
    rows = classic_rows()
    assert rows
    identifiers = [row["id"] for row in rows]
    assert len(identifiers) == len(set(identifiers))
    for row in rows:
        codes = [code.strip() for code in row["directions"].split(";") if code.strip()]
        assert codes, row["id"]
        assert set(codes) <= seed_direction_codes, row["id"]


def test_classic_venues_and_years_are_configured(seed_venue_abbrs):
    for row in classic_rows():
        assert row["title"].strip(), row["id"]
        assert row["venue"].strip() in seed_venue_abbrs, row["id"]
        assert row["year"].isdigit(), row["id"]
