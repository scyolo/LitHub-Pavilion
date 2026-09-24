"""Pages staging must not copy unreferenced files merely because their names look hashed."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.services.snapshot import export_snapshot, validate_snapshot

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
