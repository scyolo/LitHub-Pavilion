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
    ("systems", "Serverless Computing with Microservices"),
    ("graph", "Graph Neural Networks for Knowledge Graph Completion"),
    ("graph", "Graph Representation Learning with Message Passing"),
    ("multimodal", "Vision-Language Models for Visual Question Answering"),
    ("network", "Congestion Control for Data Center Networks"),
    ("network", "Software-Defined Networking with Programmable Switches"),
    ("architecture", "A RISC-V Out-of-Order Processor with Vector Extensions"),
    ("security", "Differential Privacy for Secure Aggregation"),
])
def test_requested_directions_have_real_matching_rules(code, title):
    rules = [(1, r["keyword"], float(r["weight"]), r["field"])
             for r in rows("direction_rules.csv") if r["direction_code"] == code]
    assert score_text(rules, title, None).get(1, 0) >= 2


@pytest.mark.parametrize("code,title", [
    ("hci", "Protein Interaction Networks and Gene Expression"),
    ("generative", "Thermal Diffusion in Composite Materials"),
    ("systems", "Kernel Methods for Distributed Representations"),
    ("systems", "Energy Storage Systems for Power Grids"),
    ("graph", "A Bibliography of Graphical User Interface Design"),
    ("network", "Graph Neural Networks for Molecular Property Prediction"),
    ("network", "TCP: Textual-based Class-aware Prompt Tuning for Vision-Language Models"),
    ("network", "P4: Plug-and-Play Discrete Prompting for Large Language Models"),
    ("network", "ParameterNet: Visual Pretraining for Mobile Networks"),
    ("network", "How to Protect Yourself from 5G Radiation?"),
    ("network", "Dynamic Neural Networks Across Diverse Network Topologies"),
    ("network", "Multi-agent Perception via a Robust Communication Network"),
    ("architecture", "Quantum Algorithms for Combinatorial Optimization"),
    ("architecture", "Robust Out-of-Order Retrieval for Grid-Based Storage"),
    ("architecture", "Hardware-Aware Parallel Prompt Decoding for LLM Inference"),
    ("security", "Privacy Attitudes in Social Media Communities"),
    ("security", "Sandboxing DNN-Based Controllers in Stochastic Games"),
    ("systems", "SSD: Making Face Forgery Clues Evident Again"),
    ("systems", "Generative Deduplication for Social Media Data Selection"),
    ("systems", "Multi-Task Reinforcement Learning Through Task Scheduling"),
])
def test_new_directions_do_not_use_ambiguous_single_word_rules(code, title):
    rules = [(1, r["keyword"], float(r["weight"]), r["field"])
             for r in rows("direction_rules.csv") if r["direction_code"] == code]
    assert score_text(rules, title, None).get(1, 0) < 2


def test_multimodal_identity_is_retained_while_label_is_expanded():
    directions = {d["code"]: d for d in rows("directions.csv")}
    assert set(directions) == {
        "llm", "inference", "specdec", "agent", "cv", "multimodal", "rl", "nlp",
        "retrieval", "alignment", "ml", "dl", "ai", "hci", "generative", "systems", "graph",
        "federated", "transformer", "network", "architecture", "security",
    }
    assert directions["multimodal"]["name"] == "多模态与视觉语言"
    assert directions["hci"]["name"] == "人机交互与可视化"
    assert directions["federated"]["name"] == "联邦学习"
    assert directions["transformer"]["name"] == "Transformer 架构"


def test_direction_venue_mappings_only_target_known_ab_papers():
    venues = {v["abbr"]: v for v in rows("venues.csv")}
    directions = {d["code"] for d in rows("directions.csv")}
    mappings = rows("direction_venues.csv")
    assert len(mappings) == 105
    assert len({(m["direction_code"], m["venue_abbr"]) for m in mappings}) == len(mappings)
    assert {m["direction_code"] for m in mappings} == {"network", "systems", "architecture", "security"}
    for mapping in mappings:
        assert mapping["direction_code"] in directions
        assert mapping["venue_abbr"] in venues
        assert venues[mapping["venue_abbr"]]["ccf_level"] in ("A", "B")


@pytest.mark.parametrize("code,title", [
    ("federated", "Communication-Efficient Federated Learning with Non-IID Data"),
    ("federated", "FedAvg Convergence Analysis in Cross-Silo Federated Training"),
    ("federated", "Personalized Federated Fine-Tuning of Language Models"),
])
def test_federated_direction_has_real_matching_rules(code, title):
    rules = [(1, r["keyword"], float(r["weight"]), r["field"])
             for r in rows("direction_rules.csv") if r["direction_code"] == code]
    assert score_text(rules, title, None).get(1, 0) >= 2


@pytest.mark.parametrize("code,title", [
    ("federated", "Federal Spending Records and Federally Mandated Programs"),
    ("federated", "Scaffold Proteins and Molecular Assemblies"),
])
def test_federated_direction_does_not_match_ambiguous_terms(code, title):
    rules = [(1, r["keyword"], float(r["weight"]), r["field"])
             for r in rows("direction_rules.csv") if r["direction_code"] == code]
    assert score_text(rules, title, None).get(1, 0) < 2
