"""Source archives must include reader code, never generated research data."""
import importlib.util
from pathlib import Path


def test_source_archive_contains_snapshot_runtime_and_deployment_config():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("source_package", root / "scripts" / "package_source.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = {path.relative_to(root).as_posix() for path in module.source_files()}
    assert {"frontend/src/data/snapshot-engine.js", "frontend/src/data/snapshot-worker.js", "frontend/static/README.md", "docker-compose.pages.yml", ".github/workflows/pages.yml", "ARCHITECTURE.md", "LICENSE"} <= paths
    retired = {"backend/app/collectors/pdf_downloader.py", "backend/scripts/extend_topics.py", "seeds/pdf_whitelist.csv", "系统设计方案.md", "设计审查报告.md", "界面改版与验收.md", "发布验收.md"}
    assert not paths & retired
    assert not any(path.startswith("frontend/static/snapshot/") or path.endswith(".db") or path.startswith(".secrets/") for path in paths)
