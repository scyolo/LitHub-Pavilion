"""S2 补全服务：batch 查询、记录合并、oa_url 记录（链接模式核心字段）。

从 pipeline 拆出（迭代五 C1）：补全逻辑与采集编排解耦，供管线/月度刷新/链接回填复用。
"""
import logging

import httpx
from sqlalchemy.orm import Session

from app.cleaning import normalize_arxiv_id, normalize_doi
from app.collectors.dblp import stream_prefix
from app.collectors.s2 import S2Record, enrich_batch
from app.config import settings
from app.api.serializers import abstract_text, safe_http_url
from app.models import Paper, utcnow_iso
from app.ratelimit import AsyncTokenBucket

log = logging.getLogger("papertracker.enrichment")

_ENRICH_BATCH_SIZE = 500


def s2_external_id(paper: Paper) -> str | None:
    """S2 batch 的查询单元标识：DBLP key 优先，其次 DOI / arXiv ID。"""
    if paper.s2_id:
        return "CorpusId:" + paper.s2_id
    if paper.arxiv_id:
        return "ArXiv:" + paper.arxiv_id
    if paper.doi:
        return "DOI:" + paper.doi
    if paper.dblp_key:
        return "DBLP:" + paper.dblp_key
    return None


def set_oa_url_if_empty(paper: Paper, url: str | None) -> bool:
    """链接模式唯一写入口：oa_url 只在为空时记录（先到先得，不覆盖）。

    集中此逻辑避免各采集路径重复实现（迭代五 C2）。
    """
    link = safe_http_url(url)
    if link and not safe_http_url(paper.oa_url):
        paper.oa_url = link
        return True
    return False


def apply_s2_record(session: Session, paper: Paper, rec: S2Record | None) -> None:
    """把 S2 补全结果写入论文；唯一键字段写入前查重，冲突即放弃该字段。"""
    if rec is None:
        return
    if abstract_text(paper.abstract) is None and abstract_text(rec.abstract):
        paper.abstract = abstract_text(rec.abstract)
    paper.citation_count = max(0, rec.citation_count)

    def _claim(column_value, column, current):
        if current or not column_value:
            return current
        clash = (
            session.query(Paper)
            .filter(column == column_value, Paper.id != paper.id)
            .one_or_none()
        )
        return current if clash else column_value

    paper.doi = _claim(normalize_doi(rec.doi), Paper.doi, paper.doi)
    paper.arxiv_id = _claim(normalize_arxiv_id(rec.arxiv_id), Paper.arxiv_id, paper.arxiv_id)
    paper.s2_id = _claim(rec.corpus_id, Paper.s2_id, paper.s2_id)
    # 链接模式：S2 给出的 OA PDF 链接（任意合法域）只记录展示，不下载（A4）
    set_oa_url_if_empty(paper, rec.oa_pdf_url)
    # 权威归属（4.2/F-020）：externalIds.DBLP 的 stream 前缀等于本 venue 才确认
    if rec.dblp_key and paper.source == "openalex" and not paper.dblp_key:
        if stream_prefix(rec.dblp_key) == paper.venue.dblp_stream:
            clash = (
                session.query(Paper)
                .filter(Paper.dblp_key == rec.dblp_key, Paper.id != paper.id)
                .one_or_none()
            )
            if clash is None:
                paper.dblp_key = rec.dblp_key
                # S2 supplies an external identifier, not evidence of track/year acceptance.


async def enrich_papers(session: Session, papers: list[Paper], client: httpx.AsyncClient) -> dict:
    """Record successful enrichment separately from failed lookups; callers expose partial progress."""
    stats = {"enriched": 0, "failed": 0, "missing": 0}
    pairs = []
    for p in papers:
        sid = s2_external_id(p)
        if sid:
            pairs.append((p, sid))
    if not pairs:
        stats["missing"] = len(papers)
        return stats
    limiter = AsyncTokenBucket(settings.s2_rps)
    for start in range(0, len(pairs), _ENRICH_BATCH_SIZE):
        chunk = pairs[start:start + _ENRICH_BATCH_SIZE]
        ids = [sid for _p, sid in chunk]
        try:
            records = await enrich_batch(client, limiter, ids, settings.s2_api_key)
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            stats["failed"] += len(ids)
            log.warning("S2 enrichment failed (%d papers): %s", len(ids), type(exc).__name__)
            continue
        for (paper, _sid), rec in zip(chunk, records):
            apply_s2_record(session, paper, rec)
            if rec is not None:
                paper.enriched_at = utcnow_iso()
                stats["enriched"] += 1
            else:
                stats["missing"] += 1
        session.commit()
    return stats
