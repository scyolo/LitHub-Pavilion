"""Build an explicitly allowlisted source archive, never including local research data."""
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "node_modules", "dist", "data", "papers", "backups", "backup", ".mimosa", ".zcode", "artifacts", "release-artifacts"}
TEXT_SUFFIXES = {".py", ".js", ".jsx", ".json", ".css", ".html", ".csv", ".md", ".txt", ".yml", ".yaml", ".toml", ".ini", ".conf"}
ROOT_FILES = {"README.md", "SECURITY.md", "CONTRIBUTING.md", "docker-compose.yml", ".gitignore", ".gitattributes", ".dockerignore", ".env.example", "发布验收.md"}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def source_files():
    paths = [ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()]
    for directory in ("backend/app", "backend/scripts", "backend/tests", "frontend/src", "seeds", "scripts", ".github"):
        for path in (ROOT / directory).rglob("*"):
            if not path.is_file() or any(part in EXCLUDE_PARTS for part in path.relative_to(ROOT).parts):
                continue
            if path.suffix in TEXT_SUFFIXES:
                paths.append(path)
    for directory in ("backend", "frontend"):
        for path in (ROOT / directory).iterdir():
            if path.is_file() and (path.suffix in TEXT_SUFFIXES or path.name in ("Dockerfile", ".dockerignore")) and not path.name.startswith(".env"):
                paths.append(path)
    return sorted(set(paths))


def main():
    files = source_files()
    manifest = []
    for path in files:
        name = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        if len(data) > 2_000_000 or b"\x00" in data:
            raise SystemExit(f"Unexpected binary/large source: {name}")
        text = data.decode("utf-8-sig")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            raise SystemExit(f"Potential credential in {name}; archive was not created")
        manifest.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    output = ROOT / "release-artifacts"
    output.mkdir(exist_ok=True)
    archive = output / "LitHub-Pavilion-source.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, path.relative_to(ROOT).as_posix())
    (output / "source-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"archive": str(archive), "files": len(files), "bytes": archive.stat().st_size, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
