"""Bounded conference discovery shared by maintenance and scheduled collection."""

import re
from dataclasses import replace

from app.collectors.catalog_conferences import conference_year
from app.collectors.crossref import API, SELECT, _fetch_inventory, identify_venue, item_to_raw, request_with_retry
from app.ratelimit import AsyncTokenBucket


def container_filter(item):
    isbn = next((s for s in item.get("ISBN", []) if isinstance(s, str) and re.fullmatch(r"[0-9X-]{10,17}", s)), None)
    if isbn:
        return "isbn:" + isbn
    titles = item.get("container-title") or []
    if len(titles) == 1 and not any(c in titles[0] for c in (",", ":")):
        return "container-title:" + titles[0]
    return None


def discovery_queries(venue, year):
    aliases = {
        "SenSys": "ACM/IEEE International Conference on Embedded Artificial Intelligence and Sensing Systems",
        "DAC": "ACM/IEEE The Chips to Systems Conference",
    }
    return list(dict.fromkeys(filter(None, (
        f"{aliases[venue.abbr]} {year}" if venue.abbr in aliases else None,
        f"{venue.name} {year}", f"{venue.abbr} {year}",
        venue.name, venue.abbr, (getattr(venue, "dblp_stream", "") or "").rsplit("/", 1)[-1],
    ))))


async def discover_containers(client, venue, year, limiter):
    """Explicit year queries prevent older editions from hiding new containers."""
    candidates, count = {}, 0
    for query in discovery_queries(venue, year):
        await limiter.acquire()
        response = await request_with_retry(client, API + "/works", params={
            "query.container-title": query,
            "filter": (f"from-pub-date:{max(2000, year - 1)}-01-01,"
                       f"until-pub-date:{year + 1}-12-31,type:proceedings-article"),
            "rows": 100, "select": SELECT + ",ISBN",
        })
        response.raise_for_status()
        items = response.json()["message"]["items"]
        count += len(items)
        for item in items:
            if conference_year(item, venue) == year:
                exact_filter = container_filter(item)
                if exact_filter:
                    candidates[exact_filter] = item["container-title"][0]
    return candidates, count


async def fetch_discovered_inventory(client, venue, year):
    """Enumerate candidates, then independently check each DOI/source/edition.

    The discovery window is bounded; returning records does not certify that
    every publisher container was discovered.
    """
    candidates, _ = await discover_containers(client, venue, year, AsyncTokenBucket(0.5))
    records = {}
    for exact_filter, title in candidates.items():
        items = await _fetch_inventory(
            client, API + "/works", title, max(2000, year - 1), year + 1,
            extra_filter=exact_filter, max_pages=40,
        )
        for item in items:
            if conference_year(item, venue) != year or identify_venue(item, {venue.abbr: venue}) is None:
                continue
            raw = item_to_raw(item)
            if raw is None:
                continue
            raw = replace(raw, year=year, publication_date=raw.publication_date if (raw.publication_date or "").startswith(str(year)) else None)
            raw.extra.update(crossref_item=item, inventory_scope="discovered publisher containers")
            records[raw.doi] = raw
    return list(records.values())
