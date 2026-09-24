"""Public snapshots contain only reader metadata and switch versions atomically."""
import hashlib
import json
from datetime import datetime, timezone

import pytest

from app.models import CrawlLog, Paper


def load_snapshot(directory, manifest):
    catalog = json.loads((directory / manifest["catalog"]["path"]).read_text(encoding="utf-8"))
    papers = []
    for chunk in manifest["chunks"]:
        papers.extend(json.loads((directory / chunk["path"]).read_text(encoding="utf-8")))
    return catalog, papers


def test_export_matches_public_scope_and_preserves_complete_details(session_factory, db, api_catalog, tmp_path):
    from app.services.snapshot import export_snapshot, validate_snapshot

    paper = db.get(Paper, 11)
    paper.note = "PRIVATE-RESEARCH-NOTE"
    paper.pdf_path = "private/archive.pdf"
    db.add(CrawlLog(
        run_id="public-run", task_type="weekly", status="partial", papers_new=3,
        error="SECRET_API_TOKEN and internal machine path", started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T01:00:00+00:00",
    ))
    db.commit()
    manifest = export_snapshot(session_factory, tmp_path, chunk_size=2, generated_at=api_catalog["now"])
    assert manifest["schema_version"] == 1
    assert manifest["paper_count"] == 7
    assert [chunk["count"] for chunk in manifest["chunks"]] == [2, 2, 2, 1]
    assert validate_snapshot(tmp_path) == manifest
    catalog, papers = load_snapshot(tmp_path, manifest)
    assert [row["id"] for row in papers] == [11, 23, 35, 47, 59, 71, 83]
    assert len(catalog["venues"]) == 5
    assert any(venue["abbr"] == "EMPTY" for venue in catalog["venues"])
    assert any(venue["abbr"] == "BJ" and not venue["active"] for venue in catalog["venues"])
    assert catalog["last_crawl"]["status"] == "partial"
    first = papers[0]
    assert first["abstract"] == "x" * 500
    assert len(first["abstract_preview"]) == 360
    assert [author["name"] for author in first["authors"]] == ["First", "Second", "Third", "Fourth"]
    assert first["directions"] == ["llm", "specdec"]
    assert {row["code"] for row in first["direction_details"]} == {"llm", "specdec"}
    assert first["official_url"] == "https://doi.org/10.5555/radar.11"
    assert papers[-1]["oa_url"] == "https://arxiv.org/abs/2301.00456"
    assert papers[3]["oa_url"] is None
    payload = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.glob("*.json"))
    for forbidden in ("PRIVATE-RESEARCH-NOTE", "SECRET_API_TOKEN", "private/archive.pdf", '"note"', '"pdf_url"', '"pdf_path"', '"error"'):
        assert forbidden not in payload


def test_unchanged_data_keeps_revision_and_generation_time(session_factory, sample_paper, tmp_path):
    from app.services.snapshot import export_snapshot

    first = export_snapshot(session_factory, tmp_path, generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    second = export_snapshot(session_factory, tmp_path, generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert second == first


def test_empty_database_cannot_replace_existing_snapshot(session_factory, db, sample_paper, tmp_path):
    from app.services.snapshot import export_snapshot

    export_snapshot(session_factory, tmp_path)
    original = (tmp_path / "manifest.json").read_bytes()
    db.delete(sample_paper)
    db.commit()
    with pytest.raises(ValueError, match="empty"):
        export_snapshot(session_factory, tmp_path)
    assert (tmp_path / "manifest.json").read_bytes() == original


def test_empty_snapshot_is_only_explicitly_allowed(session_factory, tmp_path):
    from app.services.snapshot import export_snapshot, validate_snapshot

    with pytest.raises(ValueError, match="empty"):
        export_snapshot(session_factory, tmp_path)
    result = export_snapshot(session_factory, tmp_path, allow_empty=True)
    assert result["paper_count"] == 0
    assert result["chunks"] == []
    assert validate_snapshot(tmp_path) == result


def test_failed_export_keeps_old_manifest_and_referenced_files(session_factory, db, sample_paper, tmp_path, monkeypatch):
    from app.services import snapshot

    previous = snapshot.export_snapshot(session_factory, tmp_path)
    original = (tmp_path / "manifest.json").read_bytes()
    sample_paper.title = "Changed title"
    db.commit()
    write = snapshot._write_content

    def fail_papers(directory, prefix, content):
        if prefix == "papers":
            raise OSError("simulated storage failure")
        return write(directory, prefix, content)

    monkeypatch.setattr(snapshot, "_write_content", fail_papers)
    with pytest.raises(OSError):
        snapshot.export_snapshot(session_factory, tmp_path)
    assert (tmp_path / "manifest.json").read_bytes() == original
    assert snapshot.validate_snapshot(tmp_path) == previous


def test_previous_revision_files_remain_usable(session_factory, db, sample_paper, tmp_path):
    from app.services.snapshot import export_snapshot

    previous = export_snapshot(session_factory, tmp_path)
    sample_paper.title = "Changed title"
    db.commit()
    latest = export_snapshot(session_factory, tmp_path)
    assert previous["revision"] != latest["revision"]
    assert load_snapshot(tmp_path, previous)[1][0]["title"] != load_snapshot(tmp_path, latest)[1][0]["title"]


@pytest.mark.parametrize("mutation", ["hash", "count", "path", "missing", "version", "revision", "generation"])
def test_validator_rejects_corruption(session_factory, sample_paper, tmp_path, mutation):
    from app.services.snapshot import export_snapshot, validate_snapshot

    manifest = export_snapshot(session_factory, tmp_path)
    if mutation == "hash":
        (tmp_path / manifest["chunks"][0]["path"]).write_text("[]", encoding="utf-8")
    elif mutation == "count":
        manifest["paper_count"] += 1
    elif mutation == "path":
        manifest["chunks"][0]["path"] = "../private.json"
    elif mutation == "missing":
        (tmp_path / manifest["chunks"][0]["path"]).unlink()
    elif mutation == "version":
        manifest["schema_version"] = 99
    elif mutation == "revision":
        manifest["revision"] = "0" * 64
    else:
        manifest["generated_at"] = "not-a-timestamp"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_snapshot(tmp_path)


def test_export_uses_content_hashes(session_factory, sample_paper, tmp_path):
    from app.services.snapshot import export_snapshot

    manifest = export_snapshot(session_factory, tmp_path)
    for entry in [manifest["catalog"], *manifest["chunks"]]:
        content = (tmp_path / entry["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
        assert entry["sha256"] in entry["path"]


def test_snapshot_rejects_non_finite_values_and_duplicate_ids(session_factory, sample_paper, tmp_path):
    from app.services.snapshot import export_snapshot, validate_snapshot, manifest_revision

    manifest = export_snapshot(session_factory, tmp_path)
    entry = manifest["chunks"][0]
    papers = json.loads((tmp_path / entry["path"]).read_text(encoding="utf-8"))
    papers.append(papers[0])
    content = json.dumps(papers).encode()
    sha = hashlib.sha256(content).hexdigest()
    entry.update(path=f"papers-{sha}.json", sha256=sha, count=2)
    manifest["paper_count"] = 2
    manifest["revision"] = manifest_revision(manifest)
    (tmp_path / entry["path"]).write_bytes(content)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        validate_snapshot(tmp_path)
