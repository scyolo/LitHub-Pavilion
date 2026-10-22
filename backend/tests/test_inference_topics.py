import csv
from pathlib import Path

import pytest

from app.services.tagging import score_text


def scores(title, abstract=None):
    with (Path(__file__).resolve().parents[2] / "seeds/direction_rules.csv").open(
        encoding="utf8", newline=""
    ) as stream:
        rules = [
            (r["direction_code"], r["keyword"], float(r["weight"]), r["field"])
            for r in csv.DictReader(stream)
            if r["enabled"] == "1"
        ]
    return score_text(rules, title, abstract)


@pytest.mark.parametrize(
    "title",
    [
        "FlashAttention-2: Faster Attention with Better Parallelism and Work Partitioning",
        "Medusa: Simple LLM Inference Acceleration Framework with Multiple Decoding Heads",
        "Efficient Memory Management for Large Language Model Serving with PagedAttention",
        "DistServe: Disaggregating Prefill and Decoding for Large Language Model Serving",
        "KIVI: A Tuning-Free Asymmetric 2bit Quantization for KV Cache",
    ],
)
def test_inference_direction_recognizes_verified_method_context(title):
    assert scores(title).get("inference", 0) >= 2


def test_medusa_heads_and_language_modeling_close_known_tag_gaps():
    assert (
        scores(
            "Medusa: Simple LLM Inference Acceleration Framework with Multiple Decoding Heads"
        ).get("specdec", 0)
        >= 2
    )
    assert (
        scores(
            "Fast Inference from Transformers via Speculative Decoding",
            "Large autoregressive models make language-modeling tasks expensive.",
        ).get("llm", 0)
        >= 2
    )


@pytest.mark.parametrize(
    "title",
    [
        "Robust Medusa effect across facial manipulations",
        "SpecTr: Spectral Transformer for Microscopic Hyperspectral Image Segmentation",
        "Efficient Bayesian inference in graphical models",
        "Speculative execution attacks on CPU branch prediction",
        "Draft model of climate change",
    ],
)
def test_homonyms_and_unrelated_inference_do_not_get_llm_efficiency_tags(title):
    actual = scores(title)
    assert actual.get("inference", 0) < 2
    assert actual.get("specdec", 0) < 2
