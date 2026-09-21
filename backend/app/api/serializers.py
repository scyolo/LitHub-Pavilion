"""论文卡片序列化共享层：方向聚合、作者聚合、列表/检索共用的 item 构造。

消除 papers.py 与 search.py 的重复序列化逻辑（迭代六 DRY）。
"""
import ipaddress
import re
from functools import lru_cache
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Author, Direction, Paper, PaperAuthor, PaperDirection

_UNSAFE_URL = re.compile(r"[\s\\\x00-\x1f\x7f<>\"]")
_ENCODED_CONTROL = re.compile(r"%(?:0[0-9a-f]|1[0-9a-f]|7f)", re.I)
_BAD_PERCENT = re.compile(r"%(?![0-9a-f]{2})", re.I)
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_NUMERIC_HOST = re.compile(r"(?:[0-9]+|0x[0-9a-f]+)", re.I)
_LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".localdomain")
_DOI = re.compile(r"10\.\d{4,9}/[^\s]+", re.ASCII)
_ARXIV = re.compile(
    r"(?:\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}|[a-z][a-z.-]*/\d{7})(?:v[1-9]\d*)?",
    re.I | re.ASCII,
)


@lru_cache(maxsize=1024)
def _safe_host(host: str) -> str | None:
    """有界纯函数缓存：只校验主机名，不缓存请求/数据库状态。"""
    if "%" in host or host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES):
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii").rstrip(".").lower()
        except UnicodeError:
            return None
        if host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES):
            return None
        labels = host.split(".")
        if len(labels) < 2 or len(host) > 253 or _NUMERIC_HOST.fullmatch(labels[-1]):
            return None
        if not all(_HOST_LABEL.fullmatch(label) for label in labels):
            return None
        return host
    if not address.is_global or address.is_multicast or address.is_reserved:
        return None
    return f"[{address.compressed}]" if address.version == 6 else address.compressed


def safe_http_url(value: str | None) -> str | None:
    """仅归一化外链，不请求 URL/DNS；完整URL每次仍检查凭据/端口/控制字符。"""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if not value or _UNSAFE_URL.search(value) or _ENCODED_CONTROL.search(value) or _BAD_PERCENT.search(value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
            return None
        host = parts.hostname.rstrip(".").lower()
        port = parts.port
        if len(host) > 253:
            return None
        host = _safe_host(host)
        if host is None:
            return None
        netloc = host
        if port is not None and port != (443 if parts.scheme == "https" else 80):
            netloc += f":{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except (ValueError, UnicodeError):
        return None


def doi_url(value: str | None) -> str | None:
    """接受 DOI 或常见 resolver 前缀，避免 doi.org/https://doi.org/... 双重拼接。"""
    if not value:
        return None
    value = value.strip()
    if value.lower().startswith(("http://", "https://")):
        url = safe_http_url(value)
        if not url:
            return None
        parts = urlsplit(url)
        if parts.hostname not in ("doi.org", "dx.doi.org"):
            return None
        value = parts.path.lstrip("/")
    else:
        value = re.sub(r"^doi:\s*", "", value, flags=re.I)
        value = re.sub(r"^(?:dx\.)?doi\.org/", "", value, flags=re.I)
    value = unquote(value).strip().lower()
    if not _DOI.fullmatch(value) or _UNSAFE_URL.search(value):
        return None
    if any(part in (".", "..") for part in value.split("/")):
        return None
    return safe_http_url("https://doi.org/" + quote(value, safe="/:;()-._"))


def arxiv_url(value: str | None) -> str | None:
    """只从完整合法 ID 或可信 arXiv URL 生成 abs 链接，绝不按任意子串猜测。"""
    if not value:
        return None
    value = value.strip()
    if value.lower().startswith(("http://", "https://")):
        url = safe_http_url(value)
        if not url:
            return None
        parts = urlsplit(url)
        if parts.hostname not in ("arxiv.org", "www.arxiv.org", "export.arxiv.org"):
            return None
        if not parts.path.startswith(("/abs/", "/pdf/")):
            return None
        value = parts.path[5:]
        if value.endswith(".pdf"):
            value = value[:-4]
    else:
        value = re.sub(r"^arxiv:\s*", "", value, flags=re.I)
    if not _ARXIV.fullmatch(value):
        return None
    return "https://arxiv.org/abs/" + value


@lru_cache(maxsize=32768)
def _cached_oa_link(oa_url: str | None, arxiv_id: str | None) -> str | None:
    return safe_http_url(oa_url) or arxiv_url(arxiv_id)


def oa_link(oa_url: str | None, arxiv_id: str | None) -> str | None:
    """SQL/卡片同口径；超长键不进缓存，修改URL自然形成新键，不缓存论文状态。"""
    if len(oa_url or "") + len(arxiv_id or "") >= 4096:
        return safe_http_url(oa_url) or arxiv_url(arxiv_id)
    return _cached_oa_link(oa_url, arxiv_id)


def abstract_text(value: str | None) -> str | None:
    """隐藏上游的空白/纯标点占位摘要，不改原始数据库内容。"""
    text = (value or "").strip()
    return text if any(character.isalnum() for character in text) else None


def paper_links(paper: Paper) -> dict[str, str | None]:
    official = doi_url(paper.doi)
    if not official:
        official = safe_http_url(paper.official_url)
        if official and urlsplit(official).hostname in ("doi.org", "dx.doi.org"):
            official = doi_url(official)
    if not official and paper.dblp_key:
        key = paper.dblp_key.strip()
        if (
            re.fullmatch(r"(?:conf|journals|books|reference|series)/[A-Za-z0-9._/-]+", key)
            and len(key.split("/")) >= 3
            and all(part not in ("", ".", "..") for part in key.split("/"))
        ):
            official = "https://dblp.org/rec/" + key
    return {"official_url": official, "oa_url": oa_link(paper.oa_url, paper.arxiv_id)}


def paper_mode() -> str:
    return "downloads" if settings.pdf_download_enabled else "links"


def directions_for(db: Session, paper_ids: list[int]) -> dict[int, list[str]]:
    """paper_id → 排序后的方向 code 列表（一次 IN 查询，避免 N+1）。"""
    if not paper_ids:
        return {}
    rows = (
        db.query(PaperDirection.paper_id, Direction.code)
        .join(Direction, PaperDirection.direction_id == Direction.id)
        .filter(PaperDirection.paper_id.in_(paper_ids))
        .all()
    )
    result: dict[int, list[str]] = {}
    for pid, code in rows:
        result.setdefault(pid, []).append(code)
    return result


def authors_for(db: Session, paper_ids: list[int]) -> dict[int, dict]:
    """paper_id → 首作者、总作者数与按署名顺序排列的前三位作者。"""
    if not paper_ids:
        return {}
    rows = (
        db.query(PaperAuthor.paper_id, Author.name, PaperAuthor.author_order)
        .join(Author, PaperAuthor.author_id == Author.id)
        .filter(PaperAuthor.paper_id.in_(paper_ids))
        .order_by(PaperAuthor.paper_id, PaperAuthor.author_order, Author.id)
        .all()
    )
    result: dict[int, dict] = {}
    for pid, name, order in rows:
        info = result.setdefault(pid, {"first_author": None, "authors_count": 0, "authors_preview": []})
        if order == 1 and not info["first_author"]:
            info["first_author"] = name
        info["authors_count"] += 1
        if len(info["authors_preview"]) < 3:
            info["authors_preview"].append(name)
    return result


def paper_card(
    paper: Paper,
    directions: dict[int, list[str]],
    authors: dict[int, dict],
) -> dict:
    """列表/检索共用的论文卡片 dict；venue 经 Paper.venue lazy="joined" 已加载。

    检索结果在此基础上额外附加 bm25 score（调用方自行添加）。
    """
    info = authors.get(paper.id, {})
    return {
        "id": paper.id,
        "title": paper.title,
        "venue": paper.venue.abbr,
        "venue_name": paper.venue.name,
        "venue_type": paper.venue.type,
        "level": paper.ccf_level,
        "year": paper.year,
        "abstract_preview": (abstract_text(paper.abstract) or "")[:360] or None,
        "authors_preview": info.get("authors_preview", []),
        "publication_date": paper.publication_date,
        "created_at": paper.created_at,
        "venue_confirmed": bool(paper.venue_confirmed),
        "directions": sorted(directions.get(paper.id, [])),
        "first_author": info.get("first_author"),
        "authors_count": info.get("authors_count", 0),
        "citation_count": paper.citation_count,
        "pdf_status": paper.pdf_status,
        "pdf_source": paper.pdf_source,
        "doi": paper.doi,
        **paper_links(paper),
    }
