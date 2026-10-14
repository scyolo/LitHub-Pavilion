"""Reject an oversized or unsafe complete GitHub Pages build before upload."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.snapshot import MAX_PAGES_SITE_BYTES


def check_pages_size(directory: Path, *, max_bytes: int = MAX_PAGES_SITE_BYTES) -> dict:
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_PAGES_SITE_BYTES:
        raise ValueError("The site limit must be positive and cannot exceed the Pages host limit")
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Symlinks are not allowed in the Pages build")
    if not directory.is_dir():
        raise ValueError("A built Pages site directory is required")
    root = directory.resolve()
    if not (root / "index.html").is_file():
        raise ValueError("The Pages build must contain index.html")
    total = count = 0
    for path in root.rglob("*"):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Symlinks and paths outside the Pages build are not allowed")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Only regular files are allowed in the Pages build")
        count += 1
        total += path.stat().st_size
        if total > max_bytes:
            raise ValueError(f"The complete Pages site exceeds its size limit: {total} > {max_bytes} bytes")
    return {"files": count, "bytes": total, "max_bytes": max_bytes, "headroom_bytes": max_bytes - total}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        result = check_pages_size(args.directory)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
