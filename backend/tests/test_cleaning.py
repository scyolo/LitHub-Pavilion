"""清洗工具测试：标题、作者、DOI、arXiv 标识和摘要重建。"""
import pytest

from app.cleaning import (
    clean_author_name,
    clean_title,
    normalize_arxiv_id,
    normalize_doi,
    normalize_title,
    rebuild_abstract,
)


@pytest.mark.parametrize("title,expected", [
    ("  Fast---Inference\tvia\nDecoding!  ", "fast inference via decoding"),
    ("Cafe\u0301Net: naïve retrieval", "cafenet naive retrieval"),
    ("ＦｌａｓｈAttention 𝟚", "flashattention 2"),
    ("𝔹-based ﬂow Kernels", "b based flow kernels"),
    ("α-model 中文检索", "model"),
    ("x\u034fy", "x y"),
    ("\u0301\u0308", ""),
    ("", ""),
])
def test_title_normalization_preserves_unicode_and_token_boundaries(title, expected):
    assert normalize_title(title) == expected


def test_clean_title_strips_trailing_dot():
    assert clean_title("Attention Is All You Need.") == "Attention Is All You Need"


def test_author_normalization():
    assert clean_author_name("Adam Zhao") == "Zhao, Adam"
    assert clean_author_name("Yann LeCun") == "LeCun, Yann"
    assert clean_author_name("Single") == "Single"
    assert clean_author_name("Zhao, Adam") == "Zhao, Adam"


def test_normalize_doi():
    assert normalize_doi("HTTPS://DOI.ORG/10.5555/X.Y") == "10.5555/x.y"
    assert normalize_doi("doi:10.1/a") == "10.1/a"
    assert normalize_doi(None) is None


def test_normalize_arxiv_id():
    assert normalize_arxiv_id("2401.12345") == "2401.12345"
    assert normalize_arxiv_id("https://arxiv.org/abs/2401.12345v2") == "2401.12345"
    assert normalize_arxiv_id("https://arxiv.org/pdf/2211.11639.pdf") == "2211.11639"
    assert normalize_arxiv_id("not-an-id") is None


def test_rebuild_abstract():
    inv = {"We": [0], "propose": [1], "speculative": [2], "decoding": [3]}
    assert rebuild_abstract(inv) == "We propose speculative decoding"
    assert rebuild_abstract(None) is None
