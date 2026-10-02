"""Bounded discovery, unlike strict registry enumeration, tolerates overlapping search hits.

Every emitted article has an exact container title. The caller still verifies
conference identity and year. This adapter never certifies complete coverage.
"""

from app.cleaning import normalize_doi
from app.collectors.crossref import API, SELECT, request_with_retry
from app.ratelimit import AsyncTokenBucket


async def fetch_bounded_container(
    client,
    title,
    year_from,
    year_to,
    *,
    on_page,
    page_size=1000,
    max_pages=10,
    article_type="proceedings-article",
):
    if (
        not 1 <= page_size <= 1000
        or not 1 <= max_pages <= 10
        or page_size * max_pages > 10000
    ):
        raise ValueError("Invalid bounded search size")
    if article_type not in ("proceedings-article", "book-chapter"):
        raise ValueError("Unsupported article type")
    if (
        not isinstance(title, str)
        or not title.strip()
        or not 2000 <= year_from <= year_to <= 2100
    ):
        raise ValueError("Invalid container/year scope")
    stats = {
        "complete": False,
        "requests": 0,
        "exact_hits": 0,
        "overlapping_hits": 0,
        "stop_reason": "page_bound",
    }
    seen = set()
    empty_fresh = 0
    limiter = AsyncTokenBucket(1)
    for page in range(max_pages):
        await limiter.acquire()
        response = await request_with_retry(
            client,
            API + "/works",
            params={
                "query.container-title": title,
                "filter": f"from-pub-date:{year_from}-01-01,until-pub-date:{year_to}-12-31,type:{article_type}",
                "sort": "score",
                "rows": page_size,
                "offset": page * page_size,
                "select": SELECT,
            },
        )
        response.raise_for_status()
        message = response.json().get("message")
        if not isinstance(message, dict) or not isinstance(message.get("items"), list):
            raise ValueError("Malformed search response")  # noqa: TRY004 - malformed remote data
        items = message["items"]
        stats["requests"] += 1
        exact = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Malformed search record")  # noqa: TRY004 - malformed remote data
            doi = normalize_doi(item.get("DOI"))
            if not doi:
                raise ValueError("Search record lacks identifier")
            if item.get("container-title") == [title]:
                exact.append((doi, item))
        if not exact:
            stats["stop_reason"] = "no_target_hits"
            break
        fresh = []
        for doi, item in exact:
            if doi in seen:
                stats["overlapping_hits"] += 1
            else:
                seen.add(doi)
                fresh.append(item)
        if fresh:
            on_page(fresh)
        stats["exact_hits"] = len(seen)
        empty_fresh = empty_fresh + 1 if not fresh else 0
        if empty_fresh >= 2:
            stats["stop_reason"] = "repeated_pages"
            break
        if len(items) < page_size:
            stats["stop_reason"] = "search_exhausted"
            break
    return stats
