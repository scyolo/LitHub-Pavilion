"""PDF 多渠道下载器（4.1 解析链 + 6.4 SSRF 防护）：

候选（去重）→ 白名单域过滤 → 优先级排序 → SSRF 校验（https、白名单、DNS 解析后
拒绝私网/保留地址、重定向逐跳复检）→ 下载（3s 间隔、.part 原子写、%PDF 魔数校验）。
主机级熔断：下载失败的 host 在 30 分钟内跳过。
"""
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.cleaning import title_slug
from app.config import settings
from app.ratelimit import MinInterval
from app.security import PdfUrlRejected, validate_pdf_url

# host → 优先级（越小越优先）：arXiv > 会议官方库 > 期刊 OA
_PRIORITY = {
    "arxiv.org": 0, "export.arxiv.org": 0,
    "proceedings.neurips.cc": 1, "papers.nips.cc": 1,
    "proceedings.mlr.press": 1,
    "openreview.net": 1,
    "aclanthology.org": 1,
    "openaccess.thecvf.com": 1,
    "ojs.aaai.org": 1,
    "ijcai.org": 1,
    "jmlr.org": 1, "jmlr.csail.mit.edu": 1,
}
_HOST_FAIL_TTL_S = 30 * 60
_MAX_REDIRECTS = 3
_CHUNK = 65536


def pdf_source_for_host(host: str) -> str:
    mapping = {
        "arxiv.org": "arxiv", "export.arxiv.org": "arxiv",
        "proceedings.neurips.cc": "neurips", "papers.nips.cc": "neurips",
        "proceedings.mlr.press": "pmlr",
        "openreview.net": "openreview",
        "aclanthology.org": "anthology",
        "openaccess.thecvf.com": "cvf",
        "ojs.aaai.org": "aaai",
        "ijcai.org": "ijcai",
        "jmlr.org": "jmlr", "jmlr.csail.mit.edu": "jmlr",
    }
    return mapping.get(host, "other_oa")


@dataclass
class DownloadResult:
    ok: bool
    path: str | None = None      # 相对 papers_root
    pdf_source: str | None = None
    error: str | None = None


class HostCircuitBreaker:
    """运行级主机熔断：失败的 host 在 TTL 内跳过。"""

    def __init__(self, ttl_s: float = _HOST_FAIL_TTL_S):
        self.ttl_s = ttl_s
        self._failed_at: dict[str, float] = {}

    def is_open(self, host: str) -> bool:
        failed_at = self._failed_at.get(host)
        return failed_at is not None and (time.monotonic() - failed_at) < self.ttl_s

    def trip(self, host: str) -> None:
        self._failed_at[host] = time.monotonic()


def dedupe_candidates(urls: list[str | None]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if not u:
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def rank_candidates(urls: list[str], whitelist: set[str]) -> list[str]:
    """过滤白名单 + 按优先级排序（未知 host 丢弃，白名单外一律不下载）。"""
    scored: list[tuple[int, str]] = []
    for url in urls:
        host = (httpx.URL(url).host or "").lower().strip(".")
        matched = next((w for w in whitelist if host == w or host.endswith("." + w)), None)
        if matched is None:
            continue
        scored.append((_PRIORITY.get(matched, 9), url))
    return [u for _, u in sorted(scored, key=lambda t: t[0])]


async def _download_one(
    client: httpx.AsyncClient,
    limiter: MinInterval,
    url: str,
    dest_dir: Path,
    filename: str,
    whitelist: set[str],
) -> Path | None:
    """单候选下载（含重定向逐跳 SSRF 复检与 .part 原子写），成功返回最终路径。"""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        await limiter.acquire()
        # 请求前对当前 URL 做完整安全校验（scheme/白名单/DNS），白名单以 DB 表为单一来源
        await validate_pdf_url(current, whitelist)
        resp = await client.get(current)
        if resp.is_redirect:
            loc = resp.headers.get("location", "")
            if not loc:
                return None
            current = str(resp.next_request.url) if resp.next_request else loc
            continue
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if ctype and "pdf" not in ctype.lower():
            return None
        dest_dir.mkdir(parents=True, exist_ok=True)
        final = dest_dir / filename
        part = dest_dir / f"{filename}.part"
        first = True
        with part.open("wb") as fh:
            async for chunk in resp.aiter_bytes(_CHUNK):
                if first:
                    if not chunk.lstrip().startswith(b"%PDF"):
                        part.unlink(missing_ok=True)
                        return None
                    first = False
                fh.write(chunk)
        if first:  # 空文件
            part.unlink(missing_ok=True)
            return None
        part.replace(final)  # os.rename 原子替换
        return final
    return None


class PdfDownloader:
    def __init__(self, papers_root: Path, whitelist: set[str]):
        self.papers_root = papers_root
        self.whitelist = whitelist
        self.limiter = MinInterval(settings.arxiv_interval_s)
        self.breaker = HostCircuitBreaker()

    def candidates_for(self, oa_pdf_url: str | None, arxiv_id: str | None) -> list[str]:
        # arXiv 双域名直链互为降级（export 子域在部分网络环境不可达，实测 2026-09-19）
        direct = (
            [f"https://export.arxiv.org/pdf/{arxiv_id}", f"https://arxiv.org/pdf/{arxiv_id}"]
            if arxiv_id
            else []
        )
        return rank_candidates(dedupe_candidates(direct + [oa_pdf_url]), self.whitelist)

    async def download(
        self,
        client: httpx.AsyncClient,
        paper_id: int,
        title: str,
        candidates: list[str],
        archive_subpath: str = "",
    ) -> DownloadResult:
        """candidates 已按优先级排序；任一成功即返回。全部失败返回 ok=False。

        archive_subpath：归档子目录（如 "llm/NeurIPS/2024"，设计 4.3），空则落根目录。
        """
        slug = title_slug(title)
        filename = f"{paper_id:06d}_{slug}.pdf"
        dest_dir = self.papers_root / archive_subpath if archive_subpath else self.papers_root
        last_error = "no_candidate"
        for url in candidates:
            host = (httpx.URL(url).host or "").lower()
            if self.breaker.is_open(host):
                last_error = f"host_circuit_open:{host}"
                continue
            try:
                path = await _download_one(
                    client, self.limiter, url, dest_dir, filename, self.whitelist
                )
            except (PdfUrlRejected, httpx.HTTPError, OSError) as exc:
                self.breaker.trip(host)
                last_error = f"{type(exc).__name__}: {host}"
                continue
            if path is None:
                self.breaker.trip(host)
                last_error = f"not_pdf_or_empty:{host}"
                continue
            rel = path.relative_to(self.papers_root).as_posix()
            return DownloadResult(True, rel, pdf_source_for_host(host), None)
        return DownloadResult(False, None, None, last_error)
