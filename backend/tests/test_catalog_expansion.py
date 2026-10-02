import csv
from collections import Counter
from pathlib import Path

import pytest

from app.services.tagging import score_text

SEEDS = Path(__file__).resolve().parents[2] / "seeds"


def rows(name):
    with (SEEDS / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_catalog_covers_all_ten_ccf_areas_without_duplicate_streams():
    venues = rows("venues.csv")
    # The 2026 directory cross-lists TOMM and DKE: one source, not two paper feeds.
    assert len(venues) == 338
    assert Counter((v["ccf_level"], v["type"]) for v in venues) == {
        ("A", "conf"): 58, ("B", "conf"): 132,
        ("A", "journal"): 37, ("B", "journal"): 111,
    }
    assert len({v["abbr"] for v in venues}) == len(venues)
    assert len({v["ccf_area"] for v in venues}) == 10
    streams = [v["dblp_stream"] for v in venues if v["dblp_stream"]]
    assert len(set(streams)) == len(streams)
    for name in ("CHI", "UIST", "CSCW", "OSDI", "SOSP", "SIGMOD", "VLDB", "TVCG", "TOCHI", "JASA", "JSLHR"):
        assert any(v["abbr"] == name for v in venues), name


@pytest.mark.parametrize("code,title", [
    ("hci", "Human-Computer Interaction for Accessible Visual Analytics"),
    ("hci", "Eye Tracking for Interactive Visualization"),
    ("generative", "Denoising Diffusion Models for Image Generation"),
    ("generative", "Flow Matching for Text-to-Video Generation"),
    ("systems", "Distributed Systems with Fault-Tolerant Consensus"),
    ("systems", "Operating Systems and Memory Management"),
    ("graph", "Graph Neural Networks for Knowledge Graph Completion"),
    ("graph", "Graph Representation Learning with Message Passing"),
    ("multimodal", "Vision-Language Models for Visual Question Answering"),
])
def test_requested_directions_have_real_matching_rules(code, title):
    rules = [(1, r["keyword"], float(r["weight"]), r["field"])
             for r in rows("direction_rules.csv") if r["direction_code"] == code]
    assert score_text(rules, title, None).get(1, 0) >= 2


@pytest.mark.parametrize("code,title", [
    ("hci", "Protein Interaction Networks and Gene Expression"),
    ("generative", "Thermal Diffusion in Composite Materials"),
    ("systems", "Kernel Methods for Distributed Representations"),
    ("graph", "A Bibliography of Graphical User Interface Design"),
])
def test_new_directions_do_not_use_ambiguous_single_word_rules(code, title):
    rules = [(1, r["keyword"], float(r["weight"]), r["field"])
             for r in rows("direction_rules.csv") if r["direction_code"] == code]
    assert score_text(rules, title, None).get(1, 0) < 2


def test_multimodal_identity_is_retained_while_label_is_expanded():
    directions = {d["code"]: d for d in rows("directions.csv")}
    assert len(directions) == 16
    assert directions["multimodal"]["name"] == "多模态与视觉语言"
    assert directions["hci"]["name"] == "人机交互与可视化"
