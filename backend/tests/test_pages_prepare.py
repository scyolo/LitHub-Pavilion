"""Pages staging must not copy unreferenced files merely because their names look hashed."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.services.snapshot import _json_bytes, _write_content, export_snapshot, manifest_revision, validate_snapshot

SPEC = importlib.util.spec_from_file_location("prepare_pages", Path(__file__).resolve().parents[2] / "scripts" / "prepare_pages.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_pages_stages_only_validated_public_assets(session_factory, sample_paper, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    manifest = export_snapshot(session_factory, source)
    private = b'{"secret":"DO-NOT-PUBLISH"}'
    disguised = f"papers-{hashlib.sha256(private).hexdigest()}.json"
    (source / disguised).write_bytes(private)
    (source / ".env").write_bytes(private)
    (source / "papers.db").write_bytes(private)
    assert MODULE.prepare_snapshot(source, target) == manifest
    assert not (target / disguised).exists()
    assert {path.name for path in target.iterdir()} == {"manifest.json", manifest["catalog"]["path"], manifest["chunks"][0]["path"]}


def test_pages_retains_only_a_validated_previous_revision(session_factory, sample_paper, db, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    first = export_snapshot(session_factory, source)
    sample_paper.title = "Updated paper title"
    db.commit()
    second = export_snapshot(session_factory, source)
    assert json.loads((source / "previous-manifest.json").read_text(encoding="utf-8")) == first
    MODULE.prepare_snapshot(source, target)
    assert (target / first["chunks"][0]["path"]).exists()
    assert validate_snapshot(target) == second


def test_invalid_previous_snapshot_cannot_enter_pages_artifact(session_factory, sample_paper, db, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    export_snapshot(session_factory, source)
    (source / "previous-manifest.json").write_text('{"secret":"private"}', encoding="utf-8")
    with pytest.raises(ValueError):
        MODULE.prepare_snapshot(source, target)
    assert not target.exists()


def test_failed_staging_preserves_previous_target_manifest(session_factory, sample_paper, db, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    first = export_snapshot(session_factory, source)
    MODULE.prepare_snapshot(source, target)
    sample_paper.title = "Updated title"
    db.commit()
    second = export_snapshot(session_factory, source)
    (source / second["chunks"][0]["path"]).write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        MODULE.prepare_snapshot(source, target)
    assert validate_snapshot(target) == first


def test_empty_snapshot_is_not_a_deployable_library(session_factory, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    export_snapshot(session_factory, source, allow_empty=True)
    with pytest.raises(ValueError, match="empty"):
        MODULE.prepare_snapshot(source, target)


def legacy_snapshot(session_factory, directory):
    manifest = export_snapshot(session_factory, directory)
    catalog = json.loads((directory / manifest["catalog"]["path"]).read_text(encoding="utf-8"))
    catalog.pop("overview")
    manifest["catalog"] = _write_content(directory, "catalog", _json_bytes(catalog))
    manifest["revision"] = manifest_revision(manifest)
    (directory / "manifest.json").write_bytes(_json_bytes(manifest))
    return manifest


def test_pages_builds_overview_from_the_same_legacy_revision_without_touching_source(session_factory, sample_paper, tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    legacy = legacy_snapshot(session_factory, source)
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    upgraded = MODULE.prepare_snapshot(source, target)
    catalog = json.loads((target / upgraded["catalog"]["path"]).read_text(encoding="utf-8"))
    assert "overview" in catalog
    assert upgraded["chunks"] == legacy["chunks"]
    assert upgraded["paper_count"] == legacy["paper_count"]
    assert upgraded["generated_at"] == legacy["generated_at"]
    assert upgraded["revision"] != legacy["revision"]
    assert catalog["overview"]["scopes"][0]["dashboard"]["total"] == legacy["paper_count"]
    assert catalog["overview"]["scopes"][0]["latest"][0]["id"] == sample_paper.id
    assert before == {path.name: path.read_bytes() for path in source.iterdir()}
    assert validate_snapshot(target) == upgraded
    assert json.loads((target / "previous-manifest.json").read_text(encoding="utf-8")) == legacy
    assert MODULE.prepare_snapshot(source, target) == upgraded


def test_pages_preserves_an_upgraded_previous_catalog_for_old_browser_tabs(session_factory, sample_paper, db, tmp_path):
    source = tmp_path / "source"
    first = legacy_snapshot(session_factory, source)
    first_site = tmp_path / "first-site"
    first_deployed = MODULE.prepare_snapshot(source, first_site)
    sample_paper.title = "Second publication"
    db.commit()
    second = export_snapshot(session_factory, source)
    second_site = tmp_path / "second-site"
    assert MODULE.prepare_snapshot(source, second_site) == second
    for entry in [first["catalog"], first_deployed["catalog"], *first["chunks"]]:
        assert (second_site / entry["path"]).is_file()


def test_failed_overview_upgrade_does_not_replace_active_target(session_factory, sample_paper, db, tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    first = export_snapshot(session_factory, source)
    MODULE.prepare_snapshot(source, target)
    sample_paper.title = "New legacy content"
    db.commit()
    legacy_snapshot(session_factory, source)

    def fail(*args):
        raise ValueError("Simulated overview failure")

    monkeypatch.setattr(MODULE, "ensure_snapshot_overview", fail)
    with pytest.raises(ValueError, match="overview"):
        MODULE.prepare_snapshot(source, target)
    assert validate_snapshot(target) == first
