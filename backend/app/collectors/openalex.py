"""OpenAlex 采集器：预算制限速（≤2 rps）、cursor 分页、venue source 解析、摘要重建。"""
import httpx

from app.cleaning import clean_author_name, clean_title, rebuild_abstract
from app.collectors.dblp import RawPaper
from app.ratelimit import AsyncTokenBucket

_API = "https://api.openalex.org"
_SELECT = ",".join(
    [
        "id", "doi", "title", "publication_year", "publication_date",
        "authorships", "primary_location", "locations", "best_oa_location",
        "open_access", "cited_by_count", "abstract_inverted_index", "updated_date",
    ]
)


class OpenAlexBudgetExhausted(Exception):
    """OpenAlex 预算/积分耗尽（403）或限流（429）：本轮暂停该通道（P1-10）。"""


def openalex_id_tail(url_or_id: str) -> str:
    """https://openalex.org/W2105838763 → W2105838763。"""
    tail = url_or_id.rstrip("/").rsplit("/", 1)[-1]
    return tail


async def resolve_source_id(
    client: httpx.AsyncClient, limiter: AsyncTokenBucket, name: str, mailto: str
) -> str | None:
    """按名称检索 OpenAlex source：先找归一化完全相等者，再退比率 ≥0.95 的近似者；
    都不满足则返回 None（宁可不配也不错配，如 AI 期刊 vs AI Review）。"""
    import logging

    from difflib import SequenceMatcher

    from app.cleaning import normalize_title  # 局部导入避免环

    logger = logging.getLogger("papertracker.openalex")
    await limiter.acquire()
    resp = await client.get(
        f"{_API}/sources",
        params={"search": name, "per-page": 10, "mailto": mailto, "select": "id,display_name"},
    )
    if resp.status_code in (401, 403, 429):
        raise OpenAlexBudgetExhausted(f"OpenAlex source lookup unavailable: HTTP {resp.status_code}")
    resp.raise_for_status()
    results = resp.json().get("results", [])
    want = normalize_title(name)
    if not want:
        return None
    for item in results:
        if normalize_title(item.get("display_name", "")) == want:
            tail = openalex_id_tail(item["id"])
            logger.info("OpenAlex source 精确匹配: %s -> %s (%s)", name, tail, item.get("display_name"))
            return tail
    best: tuple[float, dict] | None = None
    for item in results:
        got = normalize_title(item.get("display_name", ""))
        ratio = SequenceMatcher(None, want, got).ratio()
        if ratio >= 0.95 and (best is None or ratio > best[0]):
            best = (ratio, item)
    if best is not None:
        tail = openalex_id_tail(best[1]["id"])
        logger.info("OpenAlex source 近似匹配(%.3f): %s -> %s (%s)", best[0], name, tail, best[1].get("display_name"))
        return tail
    logger.warning("OpenAlex source 无可靠匹配: %s（请在 seeds/venues.csv 人工填写 openalex_source_id）", name)
    return None


def _oa_pdf_url(work: dict) -> str | None:
    loc = work.get("best_oa_location") or {}
    pdf = loc.get("pdf_url") if isinstance(loc, dict) else None
    if pdf:
        return pdf
    oa = work.get("open_access") or {}
    return oa.get("oa_url")


def _arxiv_id_from_locations(work: dict) -> str | None:
    """从 locations 的 arXiv 落地页/PDF 链接提取 arXiv ID（论文无 DOI 时 S2 归并的关键补全）。"""
    from app.cleaning import normalize_arxiv_id

    for loc in work.get("locations") or []:
        if not isinstance(loc, dict):
            continue
        for key in ("landing_page_url", "pdf_url"):
            url = loc.get(key) or ""
            if "arxiv.org" in url:
                aid = normalize_arxiv_id(url)
                if aid:
                    return aid
    return None


async def fetch_works_by_source(
    client: httpx.AsyncClient,
    limiter: AsyncTokenBucket,
    mailto: str,
    source_id: str,
    years: list[int],
    from_updated_date: str | None = None,
) -> list[dict]:
    """按 source.id + publication_year 过滤，cursor 分页返回原始 work dict 列表。"""
    works: list[dict] = []
    # locations.source.id（任一 location 命中目标 venue）：会议论文的 primary_location
    # 常指向其 arXiv 版，用 primary 过滤会漏掉大量正式版论文（召回率问题，见设计 4.2）
    filters = [f"locations.source.id:{source_id}" if source_id.startswith("S") else f"locations.source.issn:{source_id}"]
    year_list = "|".join(str(y) for y in years)
    filters.append(f"publication_year:{year_list}")
    if from_updated_date:
        filters.append(f"from_updated_date:{from_updated_date}")
    cursor = "*"
    seen_cursors: set[str] = set()
    while cursor:
        if cursor in seen_cursors or len(seen_cursors) >= 1000:
            raise ValueError("OpenAlex pagination repeated or exceeded the safety limit")
        seen_cursors.add(cursor)
        await limiter.acquire()
        resp = await client.get(
            f"{_API}/works",
            params={
                "filter": ",".join(filters),
                "cursor": cursor,
                "per-page": 200,
                "select": _SELECT,
                "mailto": mailto,
            },
        )
        if resp.status_code in (403, 429):
            raise OpenAlexBudgetExhausted(f"openalex_budget_or_ratelimit: HTTP {resp.status_code}")
        resp.raise_for_status()
        body = resp.json()
        works.extend(body.get("results", []))
        cursor = (body.get("meta") or {}).get("next_cursor")
    return works


def work_to_raw_paper(work: dict, official_url_fallback: str) -> tuple[str, RawPaper | None]:
    """OpenAlex work → (openalex_id_tail, RawPaper)。无标题的丢弃。"""
    oid = openalex_id_tail(work.get("id", ""))
    title = clean_title(work.get("title") or work.get("display_name") or "")
    if not oid or not title:
        return oid or "", None
    authors = [
        clean_author_name((a.get("author") or {}).get("display_name", ""))
        for a in work.get("authorships", [])
        if isinstance(a, dict)
    ]
    doi = work.get("doi")
    if doi:
        from app.cleaning import normalize_doi

        doi = normalize_doi(doi)
    return oid, RawPaper(
        source="openalex",
        venue_key=oid,
        title=title,
        year=int(work.get("publication_year") or 0),
        authors=[a for a in authors if a],
        doi=doi,
        arxiv_id=_arxiv_id_from_locations(work),
        publication_date=work.get("publication_date"),
        official_url=doi and f"https://doi.org/{doi}" or official_url_fallback,
        extra={
            "abstract": rebuild_abstract(work.get("abstract_inverted_index")),
            "cited_by_count": int(work.get("cited_by_count") or 0),
            "oa_pdf": _oa_pdf_url(work),
            "updated_date": work.get("updated_date"),
        },
    )
