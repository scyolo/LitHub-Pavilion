"""DBLP TOC adapter; search results identify records, not a time-based cursor."""
from dataclasses import dataclass, field

import httpx

from app.cleaning import clean_author_name, clean_title
from app.ratelimit import AsyncTokenBucket

_ANUBIS_MARKERS = ("/.within.website", "making sure you", "you're not a bot")
_H = 1000


@dataclass
class ProbeResult:
    ok: bool
    reason: str


@dataclass
class RawPaper:
    source: str
    venue_key: str
    title: str
    year: int
    authors: list[str] = field(default_factory=list)
    doi: str | None = None
    arxiv_id: str | None = None
    publication_date: str | None = None
    mdate: str | None = None
    official_url: str | None = None
    extra: dict = field(default_factory=dict)


def build_toc_query(toc_key: str) -> str:
    return f"toc:db/{toc_key}.bht:"


def toc_key_for(venue_stream: str, toc_pattern: str, year: int) -> str:
    return f"{venue_stream}/{toc_pattern.format(year=year)}"


def _looks_like_challenge(response: httpx.Response) -> bool:
    return any(marker in response.text[:5000].lower() for marker in _ANUBIS_MARKERS)


def _hits(body: dict) -> dict:
    if not isinstance(body, dict):
        raise ValueError("Invalid DBLP JSON response")
    result = body.get("result", body)
    if not isinstance(result, dict) or not isinstance(result.get("hits"), dict):
        raise ValueError("Missing DBLP hits envelope")
    return result["hits"]


async def probe_dblp(client: httpx.AsyncClient, base_url: str, sample_toc: str = "conf/nips/nips2024") -> ProbeResult:
    try:
        response = await client.get(f"{base_url.rstrip('/')}/search/publ/api", params={
            "q": build_toc_query(sample_toc), "h": 1, "format": "json",
        })
        if _looks_like_challenge(response):
            return ProbeResult(False, "dblp=challenge; fallback requested")
        response.raise_for_status()
        _hits(response.json())
        return ProbeResult(True, "dblp=ok")
    except (httpx.HTTPError, ValueError) as exc:
        return ProbeResult(False, f"dblp_probe_error:{type(exc).__name__}")


def _authors(info: dict) -> list[str]:
    values = (info.get("authors") or {}).get("author", [])
    if isinstance(values, (str, dict)):
        values = [values]
    return [clean_author_name(value.get("text", "") if isinstance(value, dict) else str(value)) for value in values]


async def fetch_toc(client: httpx.AsyncClient, limiter: AsyncTokenBucket, base_url: str, toc_key: str) -> list[RawPaper]:
    papers = []
    offset = 0
    while True:
        await limiter.acquire()
        response = await client.get(f"{base_url.rstrip('/')}/search/publ/api", params={
            "q": build_toc_query(toc_key), "h": _H, "f": offset, "format": "json",
        })
        if _looks_like_challenge(response):
            raise ValueError("DBLP returned a challenge page")
        response.raise_for_status()
        hits = _hits(response.json())
        batch = hits.get("hit") or []
        if isinstance(batch, dict):
            batch = [batch]
        total = int(hits.get("@total", len(batch)))
        if not batch:
            if offset < total:
                raise ValueError("DBLP pagination ended before advertised total")
            break
        for hit in batch:
            info = hit.get("info") or {}
            key, title = info.get("key"), clean_title(info.get("title", ""))
            try:
                year = int(info.get("year", 0))
            except (ValueError, TypeError):
                continue
            if not key or not title or not 2000 <= year <= 2100:
                continue
            papers.append(RawPaper(
                source="dblp", venue_key=key, title=title, year=year, authors=_authors(info),
                doi=info.get("doi"), mdate=hit.get("@mdate"),
                official_url=f"https://dblp.org/rec/{key}",
                extra={"provenance": "dblp_toc"},
            ))
        offset += len(batch)
        if offset >= total:
            break
    return papers


def stream_prefix(dblp_key: str) -> str:
    return "/".join(dblp_key.split("/")[:-1])
