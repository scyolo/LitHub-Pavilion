"""Semantic Scholar batch 补全器（500 篇/请求）：摘要/引用/DOI/arXiv/DBLP externalIds/OA 链接。"""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.collectors.dblp import RawPaper
    from app.models import Venue

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.collectors.http_client import make_client as _make_client
from app.ratelimit import AsyncTokenBucket

_API = "https://api.semanticscholar.org/graph/v1/paper/batch"
_BULK_API = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_FIELDS = "title,abstract,externalIds,citationCount,isOpenAccess,openAccessPdf,year,authors"
_BULK_FIELDS = _FIELDS + ",publicationDate"


@dataclass
class S2Record:
    paper_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    dblp_key: str | None = None
    corpus_id: str | None = None
    citation_count: int = 0
    oa_pdf_url: str | None = None
    publication_date: str | None = None
    authors: list[str] = field(default_factory=list)


class S2RateLimited(RuntimeError):
    pass


def _parse(item: dict) -> S2Record:
    ext = item.get("externalIds") or {}
    oa = item.get("openAccessPdf") or {}
    return S2Record(
        paper_id=item.get("paperId"),
        title=item.get("title"),
        abstract=item.get("abstract"),
        doi=ext.get("DOI"),
        arxiv_id=ext.get("ArXiv"),
        dblp_key=ext.get("DBLP"),
        corpus_id=str(ext["CorpusId"]) if ext.get("CorpusId") else None,
        citation_count=int(item.get("citationCount") or 0),
        oa_pdf_url=(oa or {}).get("url"),
        publication_date=item.get("publicationDate"),
        authors=[a.get("name", "") for a in item.get("authors", []) if isinstance(a, dict)],
    )


@retry(
    retry=retry_if_exception_type((httpx.TransportError, S2RateLimited)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=5, max=300),
    reraise=True,
)
async def enrich_batch(
    client: httpx.AsyncClient,
    limiter: AsyncTokenBucket,
    ids: list[str],
    api_key: str,
) -> list[S2Record | None]:
    """ids 形如 DBLP:conf/nips/xxx / DOI:10.xxx / ArXiv:2401.12345，返回按输入对齐。"""
    if not ids:
        return []
    if len(ids) > 500:
        raise ValueError("S2 batch allows at most 500 identifiers")
    await limiter.acquire()
    headers = {"x-api-key": api_key} if api_key else {}
    resp = await client.post(_API, params={"fields": _FIELDS}, json={"ids": ids}, headers=headers)
    if resp.status_code == 429 or resp.status_code >= 500:
        raise S2RateLimited(f"HTTP {resp.status_code}")
    if resp.status_code == 400:
        # S2 行为：整批没有任何可解析 ID 时返回 400 "No valid paper ids given"
        # ——语义为"全部未知"，返回全 None，不作错误重试
        body = {}
        try:
            body = resp.json()
        except ValueError:
            pass
        if "No valid paper ids" in str(body.get("error", "")):
            return [None] * len(ids)
    resp.raise_for_status()
    items = resp.json()
    if not isinstance(items, list) or len(items) != len(ids):
        raise ValueError("S2 batch response is not aligned with the requested identifiers")
    return [_parse(it) if isinstance(it, dict) else None for it in items]


@retry(
    retry=retry_if_exception_type((httpx.TransportError, S2RateLimited)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=5, max=300),
    reraise=True,
)
async def bulk_search_venue_year(
    client: httpx.AsyncClient,
    limiter: AsyncTokenBucket,
    query: str,
    venue: str,
    year: int,
    api_key: str,
    token: str | None = None,
) -> dict:
    """S2 bulk search（venue+year 过滤，≤1000 条/页，token 翻页）。

    返回原始响应 dict（data + token）；429/5xx 指数退避。
    """
    await limiter.acquire()
    headers = {"x-api-key": api_key} if api_key else {}
    params: dict = {
        # Semantic Scholar treats an omitted/empty query as the complete
        # venue+year inventory. Do not force a topic query here: topic
        # queries are only supplementary recall probes.
        "venue": venue,
        "year": str(year),
        "fields": _BULK_FIELDS,
        "limit": 1000,
    }
    if query.strip():
        params["query"] = query.strip()
    if token:
        params["token"] = token
    resp = await client.get(_BULK_API, params=params, headers=headers)
    if resp.status_code == 429 or resp.status_code >= 500:
        raise S2RateLimited(f"HTTP {resp.status_code}")
    resp.raise_for_status()
    return resp.json()


class S2BulkCoverageIncomplete(RuntimeError):
    """The bulk endpoint still had a continuation token at the safety limit."""


async def fetch_bulk_raw_papers(
    venue: "Venue",
    year: int,
    queries: list[str] | None,
    api_key: str,
    s2_rps: float,
    max_pages_per_query: int = 100,
) -> list["RawPaper"]:
    """Fetch the complete S2 venue/year inventory plus optional recall probes.

    The empty-query request is mandatory and is the coverage-bearing request.
    Configured topic queries are supplementary only; they cannot make a run look
    complete if the full request fails. A matching DBLP identifier associates a
    record with the configured proceedings stream; it is also the evidence used
    to keep arXiv-only records out of the CCF venue collection.
    """
    from app.collectors.dblp import RawPaper, stream_prefix
    from app.cleaning import clean_author_name, is_noise_title, normalize_title
    from app.publication import _valid_date

    limiter = AsyncTokenBucket(s2_rps)
    seen: set[str] = set()
    out: list[RawPaper] = []
    # Full venue/year inventory first. Keep configured probes after it for
    # records that S2 indexes under a slightly different query shape.
    all_queries = [""] + list(queries or [])
    all_queries = list(dict.fromkeys(query.strip() for query in all_queries))
    async with _make_client() as client:
        for query in all_queries:
            token: str | None = None
            pages = 0
            seen_tokens: set[str] = set()
            while True:
                try:
                    body = await bulk_search_venue_year(
                        client, limiter, query, venue.s2_venue, year, api_key, token
                    )
                except Exception:
                    # The empty query is the coverage-bearing request. A
                    # supplementary topic probe may be skipped without making
                    # a complete venue/year inventory partial.
                    if query:
                        break
                    raise
                if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                    raise S2BulkCoverageIncomplete("S2 returned a malformed inventory page")
                if body.get("token") and not body["data"]:
                    raise S2BulkCoverageIncomplete("S2 returned an empty page with a continuation token")
                for item in body["data"]:
                    rec = _parse(item)
                    try:
                        item_year = int(item.get("year"))
                    except (TypeError, ValueError):
                        continue
                    if not (rec.dblp_key and rec.title) or item_year != year:
                        continue
                    if stream_prefix(rec.dblp_key) != venue.dblp_stream:
                        continue  # journals/corr（arXiv-only），不归属本 venue
                    if rec.dblp_key in seen:
                        continue
                    seen.add(rec.dblp_key)
                    if is_noise_title(normalize_title(rec.title or "")):
                        continue
                    publication_date = rec.publication_date
                    # S2's publicationDate may be the arXiv submission/update
                    # date. It is safe only when it is a valid date in the
                    # proceedings year; DBLP remains the authority for year.
                    if not (
                        isinstance(publication_date, str)
                        and _valid_date(publication_date)
                        and publication_date.startswith(f"{year:04d}-")
                    ):
                        publication_date = None
                    out.append(
                        RawPaper(
                            source="dblp",
                            venue_key=rec.dblp_key,
                            title=(rec.title or "").rstrip("."),
                            year=year,
                            authors=[clean_author_name(a) for a in rec.authors],
                            doi=rec.doi,
                            arxiv_id=rec.arxiv_id,
                            publication_date=publication_date,
                            official_url="https://dblp.org/rec/" + rec.dblp_key + ".html",
                            extra={
                                "abstract": rec.abstract,
                                "cited_by_count": rec.citation_count,
                                "oa_pdf": rec.oa_pdf_url,
                                "provenance": "s2_bulk",
                                "s2_id": rec.corpus_id,
                            },
                        )
                    )
                next_token = body.get("token")
                pages += 1
                if not next_token:
                    break
                if next_token in seen_tokens or pages >= max_pages_per_query:
                    raise S2BulkCoverageIncomplete(
                        f"S2 pagination safety limit reached for {venue.s2_venue}/{year}"
                    )
                seen_tokens.add(next_token)
                token = next_token
    return out
