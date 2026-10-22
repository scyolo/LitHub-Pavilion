import json
from pathlib import Path
from types import SimpleNamespace

from app.cleaning import normalize_title
from app.models import Direction, Paper, PaperDirection
from app.services.query_aliases import keyword_query, query_topic


def test_static_and_api_alias_contracts_match_within_their_docker_contexts():
    root=Path(__file__).resolve().parents[2]
    assert json.loads((root/'seeds/query_aliases.json').read_text('utf8')) == json.loads((root/'frontend/src/data/query_aliases.json').read_text('utf8'))


def test_aliases_are_whole_queries_and_do_not_change_exact_titles():
    directions = [SimpleNamespace(code="specdec", name="投机解码", enabled=1)]
    assert query_topic("投机解码", "auto", directions).code == "specdec"
    assert query_topic("投机解码", "exact", directions) is None
    assert query_topic("speculative decoding", "auto", directions) is None
    assert keyword_query("EAGLE3") == "EAGLE 3"
    assert (
        keyword_query("EAGLE3 in a complete paper title")
        == "EAGLE3 in a complete paper title"
    )


def test_topic_search_preserves_year_and_existing_direction_intersection(
    client, db, sample_paper, sample_direction
):
    db.add(
        PaperDirection(
            paper_id=sample_paper.id,
            direction_id=sample_direction.id,
            source="rule",
            score=2,
        )
    )
    db.add(Direction(code="other", name="其他", enabled=1))
    db.commit()
    found = client.get("/api/search", params={"q": "投机解码"})
    assert found.status_code == 200, found.text
    assert found.json()["match_mode"] == "topic"
    assert found.json()["items"][0]["id"] == sample_paper.id
    assert (
        client.get("/api/search", params={"q": "投机解码", "year": 2023}).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.get(
            "/api/search", params={"q": "投机解码", "direction": "other"}
        ).json()["total"]
        == 0
    )


def test_compact_method_name_falls_back_before_unrelated_fuzzy_terms(
    client, db, sample_venue
):
    title = "EAGLE-3: Scaling up Inference Acceleration of Large Language Models"
    p = Paper(
        title=title,
        title_norm=normalize_title(title),
        source="manual",
        doi="10.5555/eagle3",
        year=2025,
        venue_id=sample_venue.id,
        ccf_level="A",
        ccf_area="人工智能",
        venue_confirmed=1,
        official_url="https://doi.org/10.5555/eagle3",
    )
    db.add(p)
    db.commit()
    result = client.get("/api/search", params={"q": "EAGLE3"}).json()
    assert result["total"] == 1 and result["items"][0]["id"] == p.id
    assert result["match_mode"] == "keywords" and result["query_rewrite"] == "EAGLE 3"
    assert (
        client.get("/api/search", params={"q": "EAGLE3", "match": "exact"}).json()[
            "total"
        ]
        == 0
    )
    # A literal hit is retained when no canonical spelling matches the scope.
    p.title = "An EAGLE3 evaluation"
    p.title_norm = normalize_title(p.title)
    db.commit()
    assert (
        client.get("/api/search", params={"q": "EAGLE3"}).json()["items"][0]["id"]
        == p.id
    )


def test_known_compact_spelling_finds_the_method_despite_other_literal_mentions(
    client, db, sample_venue
):
    titles = ["FlashAttention-2: Faster Attention", "Another attention method"]
    papers = []
    for i, title in enumerate(titles):
        paper = Paper(title=title, title_norm=normalize_title(title), source="manual",
                      doi=f"10.5555/attention.{i}", year=2024 + i,
                      venue_id=sample_venue.id, ccf_level="A", venue_confirmed=1,
                      official_url=f"https://doi.org/10.5555/attention.{i}",
                      abstract="We compare against FlashAttention2" if i else None)
        db.add(paper)
        papers.append(paper)
    db.commit()
    result = client.get("/api/search", params={"q": "FlashAttention2"}).json()
    assert result["items"][0]["id"] == papers[0].id
    assert result["query_rewrite"] == "FlashAttention 2"
    literal = client.get("/api/search", params={"q": "FlashAttention2", "match": "keywords"}).json()
    assert [p["id"] for p in literal["items"]] == [papers[1].id]
    scoped = client.get("/api/search", params={"q": "FlashAttention2", "year": 2025}).json()
    assert [p["id"] for p in scoped["items"]] == [papers[1].id]
