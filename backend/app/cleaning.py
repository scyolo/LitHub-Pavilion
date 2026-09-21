"""数据清洗工具：标题归一化、作者名规范化、DOI 规范化、slug、摘要重建。"""
import re
import unicodedata
from difflib import SequenceMatcher

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# 期刊卷首/卷尾的非论文记录（OpenAlex 会把它们当 work 收录）
NOISE_TITLES = {
    "editorial board",
    "editorial",
    "information for authors",
    "table of contents",
    "contents",
    "front matter",
    "back matter",
    "reviewers",
    "editorial notes",
    "in this issue",
    "aims and scope",
    "index to advertisers",
    "blank page",
}
# OpenAlex 实测形态常为 "期刊全称 + 卷首栏目名"（如 "IEEE TNNLS Information for Authors"）
_NOISE_SUFFIXES = (
    "information for authors",
    "editorial board",
    "editorial notes",
    "reviewers",
    "aims and scope",
    "table of contents",
)


def is_noise_title(title_norm: str) -> bool:
    """卷首噪声判定（迭代八）：期刊的 Editorial Board / Information for Authors 等非论文记录。"""
    norm = (title_norm or "").strip().lower()
    if not norm:
        return False
    if norm in NOISE_TITLES or norm.startswith("editorial board"):
        return True
    return any(norm.endswith(" " + suffix) or norm == suffix for suffix in _NOISE_SUFFIXES)


def normalize_title(title: str) -> str:
    """title_norm：lowercase + NFKD 去变音符 + 去标点/空白，用于模糊匹配与去重。"""
    text = unicodedata.normalize("NFKD", title or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return _WS.sub(" ", text)


def clean_title(title: str) -> str:
    """去 DBLP 标题尾部句点。"""
    return (title or "").strip().rstrip(".").strip()


def clean_author_name(raw: str) -> str:
    """DBLP 给 'Given Surname'（最后一个空白分隔段视为姓）→ 'Surname, Given'。"""
    name = unicodedata.normalize("NFKD", raw or "").strip()
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = _WS.sub(" ", name)
    if not name:
        return ""
    if "," in name:
        return name
    parts = name.split(" ")
    if len(parts) == 1:
        return parts[0]
    surname = parts[-1]
    given = " ".join(parts[:-1])
    return f"{surname}, {given}"


def author_name_norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _NON_ALNUM.sub("", text.lower())


def normalize_doi(doi: str | None) -> str | None:
    """lowercase、去 https://doi.org/ 前缀；空返回 None。"""
    if not doi:
        return None
    doi = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi.strip() or None


def normalize_arxiv_id(raw: str | None) -> str | None:
    """从任意 arXiv URL/ID 提取规范 ID，如 2401.12345 或 2401.12345v2 → 去 vN。"""
    if not raw:
        return None
    text = raw.strip()
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(v\d+)?", text, re.I)
    if not m:
        m = re.fullmatch(r"([0-9]{4}\.[0-9]{4,5})(v\d+)?", text)
    if not m:
        return None
    return m.group(1)


def title_slug(title: str) -> str:
    """4.3 slug 规则：NFKD→ascii→lower→非 [a-z0-9] 段→'-'→合并→截 20→去尾 '-'。"""
    text = unicodedata.normalize("NFKD", title or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _NON_ALNUM.sub("-", text.lower())
    text = re.sub(r"-+", "-", text).strip("-")
    text = text[:20].rstrip("-")
    return text or "paper"


def similar_titles(a_norm: str, b_norm: str, threshold: float = 0.95) -> bool:
    """4.2 同篇校验：norm 相等或归一化编辑距离相似度 ≥ threshold。"""
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm:
        return True
    return SequenceMatcher(None, a_norm, b_norm).ratio() >= threshold


def rebuild_abstract(inv_index: dict[str, list[int]] | None) -> str | None:
    """OpenAlex abstract_inverted_index → 纯文本摘要。"""
    if not inv_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inv_index.items():
        positions.extend((i, word) for i in idxs)
    positions.sort()
    return " ".join(w for _, w in positions) or None
