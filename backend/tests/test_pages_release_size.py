"""A complete Pages release must fit the host, not only its paper directory."""
import importlib.util
from pathlib import Path

import pytest

from app.services import snapshot

ROOT = Path(__file__).resolve().parents[2]


def size_guard():
    spec = importlib.util.spec_from_file_location("check_pages_size", ROOT / "scripts" / "check_pages_size.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_pages_size


def test_current_and_rollback_release_fit_with_reserved_ui_space():
    # Measured, allowlisted 18f4376e1446 + retained 3d798240bffd assets.
    current_bytes = 671_269_634
    previous_unique_bytes = 299_413_620
    assert current_bytes + previous_unique_bytes <= snapshot.MAX_SNAPSHOT_BYTES
    assert snapshot.MAX_SNAPSHOT_BYTES + 16 * 1024 * 1024 <= 1_000_000_000
    assert snapshot.MAX_FILE_BYTES == 8 * 1024 * 1024


def test_size_guard_counts_the_entire_site(tmp_path):
    (tmp_path / "index.html").write_bytes(b"x" * 20)
    (tmp_path / "snapshot").mkdir()
    (tmp_path / "snapshot" / "papers.json").write_bytes(b"x" * 40)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_bytes(b"x" * 30)
    result = size_guard()(tmp_path, max_bytes=100)
    assert result == {"files": 3, "bytes": 90, "max_bytes": 100, "headroom_bytes": 10}


def test_non_snapshot_assets_can_exceed_the_release_limit(tmp_path):
    (tmp_path / "index.html").write_bytes(b"x" * 20)
    (tmp_path / "papers.json").write_bytes(b"x" * 60)
    (tmp_path / "application.js").write_bytes(b"x" * 30)
    with pytest.raises(ValueError, match="site exceeds"):
        size_guard()(tmp_path, max_bytes=100)


def test_size_guard_requires_a_built_site(tmp_path):
    with pytest.raises(ValueError, match="index.html"):
        size_guard()(tmp_path)
    with pytest.raises(ValueError, match="directory"):
        size_guard()(tmp_path / "missing")


def test_size_guard_rejects_symbolic_links(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("safe", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == index or original(path))
    with pytest.raises(ValueError, match="[Ss]ymlink"):
        size_guard()(tmp_path)


@pytest.mark.parametrize("limit", [0, -1, True, 1_000_000_001])
def test_size_guard_cannot_disable_or_raise_the_host_limit(tmp_path, limit):
    (tmp_path / "index.html").write_text("safe", encoding="utf-8")
    with pytest.raises(ValueError, match="limit"):
        size_guard()(tmp_path, max_bytes=limit)
