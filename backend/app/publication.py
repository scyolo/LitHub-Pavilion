"""Comparable publication dates without inventing precision for year-only records."""
import re
from datetime import date
from functools import lru_cache


@lru_cache(maxsize=8192)
def _valid_date(value: str) -> bool:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def publication_date_key(publication_date, year) -> str:
    if isinstance(publication_date, str) and _valid_date(publication_date):
        return publication_date
    if isinstance(year, str) and re.fullmatch(r"[0-9]{4}", year):
        year = int(year)
    if type(year) is int and 1 <= year <= 9999:
        return f"{year:04d}-00-00"
    return ""


def publication_sort_key(paper) -> str:
    return publication_date_key(paper.get("publication_date"), paper.get("year"))
