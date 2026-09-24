"""Validate Pages inputs and copy only content-addressed public snapshot assets."""
import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.snapshot import MAX_FILE_BYTES, MAX_SNAPSHOT_BYTES, _read_json, _validate_contents, validate_snapshot


def prepare_snapshot(source: Path, target: Path) -> dict:
    source, target = Path(source), Path(target)
    manifest = validate_snapshot(source)
    if not manifest["paper_count"]:
        raise ValueError("Refusing to deploy an empty public paper library")
    if target.is_symlink():
        raise ValueError("Snapshot destination must not be a symlink")
    if target.exists() and (target / "manifest.json").exists():
        validate_snapshot(target)
    entries = {entry["path"]: entry["sha256"] for entry in [manifest["catalog"], *manifest["chunks"]]}
    previous_path = source / "previous-manifest.json"
    if previous_path.exists() or previous_path.is_symlink():
        previous, _ = _read_json(previous_path, max_bytes=1024 * 1024)
        try:
            _validate_contents(source, previous)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid previous public snapshot") from exc
        entries.update({entry["path"]: entry["sha256"] for entry in [previous["catalog"], *previous["chunks"]]})
    files = []
    total = 0
    for name, digest in sorted(entries.items()):
        path = source / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Unsafe snapshot asset")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Snapshot asset hash mismatch")
        total += len(content)
        if total > MAX_SNAPSHOT_BYTES:
            raise ValueError("Pages snapshot exceeds the deployment size budget")
        files.append(path)
    target.mkdir(parents=True, exist_ok=True)
    for path in files:
        destination = target / path.name
        if destination.is_symlink():
            raise ValueError("Unsafe snapshot destination")
        if destination.exists() and destination.read_bytes() != path.read_bytes():
            raise ValueError("Existing content-addressed asset is corrupt")
        if not destination.exists():
            shutil.copyfile(path, destination)
    destination = target / "manifest.json"
    if destination.is_symlink():
        raise ValueError("Unsafe snapshot manifest destination")
    from app.services.snapshot import _atomic_write

    _atomic_write(destination, (source / "manifest.json").read_bytes())
    return validate_snapshot(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--expected-revision", default="")
    args = parser.parse_args()
    source_manifest = validate_snapshot(args.source)
    if args.expected_revision and source_manifest["revision"] != args.expected_revision:
        raise ValueError("Dispatched revision does not match checked-out snapshot")
    manifest = prepare_snapshot(args.source, args.target)
    print(f"Validated {manifest['paper_count']} papers; revision {manifest['revision']}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"revision={manifest['revision']}\n")


if __name__ == "__main__":
    main()
