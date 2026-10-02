"""Build a same-origin, versioned deadline feed from CCFDDL's public YAML archive.

No visitor calls GitHub or a third-party API. Exact venue identities are matched
against our CCF directory; ambiguous acronym/DBLP matches are never guessed.
Run from the project root: python backend/scripts/sync_deadlines.py
"""
import argparse
import csv
import hashlib
import io
import ipaddress
import json
import re
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "https://github.com/ccfddl/ccf-deadlines"
ARCHIVE = "https://codeload.github.com/ccfddl/ccf-deadlines/zip/refs/heads/main"
MAX_ARCHIVE = 24 * 1024 * 1024
# Only documented spelling aliases. In particular IEEE Cloud is NOT ACM SoCC.
ALIASES = {
    "kdd": "SIGKDD", "acmmm": "ACM MM", "mm": "ACM MM", "multimedia": "ACM MM",
    "atc": "ACM SIGOPS ATC", "usenixatc": "ACM SIGOPS ATC",
    "usenixsecurity": "USENIX Security", "security": "USENIX Security",
    "ieeevr": "VR", "vr": "VR", "ieeevis": "IEEE VIS", "vis": "IEEE VIS",
    "esecfse": "FSE", "fsecrypto": "FSE (Crypto)", "fastsoftwareencryption": "FSE (Crypto)",
    "ecmlpkdd": "ECML-PKDD", "siggraphasia": "SIGGRAPH ASIA",
    "acmsigopsatc": "ACM SIGOPS ATC",
}


def normalized(value):
    return re.sub(r"[^a-z0-9+]", "", str(value).lower())


def safe_url(value):
    if not isinstance(value, str) or re.search(r'[\s\\\x00-\x1f<>\"]', value):
        return None
    try:
        url = urlparse(value)
        host = (url.hostname or "").lower().rstrip(".")
        if url.scheme not in ("http", "https") or url.username or url.password or "." not in host:
            return None
        if host.endswith((".local", ".localhost", ".localdomain")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None


def deadline_utc(value, zone):
    """Return an exact UTC instant, or None for TBD/incomplete/ambiguous inputs."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?", value):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            label = str(zone or "").strip()
            if label.lower() == "aoe":
                label = "UTC-12"
            offsets = {"UTC": 0, "GMT": 0, "PST": -8, "PDT": -7, "EST": -5, "EDT": -4, "CET": 1, "CEST": 2}
            fixed = re.fullmatch(r"UTC([+-])(\d{1,2})(?::(\d{2}))?", label, re.IGNORECASE)
            if fixed:
                hours, minutes = int(fixed[2]), int(fixed[3] or 0)
                if hours > 14 or minutes > 59:
                    return None
                tz = timezone((1 if fixed[1] == "+" else -1) * timedelta(hours=hours, minutes=minutes))
            elif label in offsets:
                tz = timezone(timedelta(hours=offsets[label]))
            else:
                tz = ZoneInfo({"PT": "America/Los_Angeles", "ET": "America/New_York"}.get(label, label))
            first, second = stamp.replace(tzinfo=tz, fold=0), stamp.replace(tzinfo=tz, fold=1)
            # Reject ambiguous/nonexistent DST clock readings instead of silently choosing a time.
            if first.utcoffset() != second.utcoffset():
                return None
            if first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != stamp:
                return None
            stamp = first
        return stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        return None


def build_feed(venues, sources, now, archive_sha256):
    configured = [v for v in venues if v["type"] == "conf" and v["ccf_level"] in ("A", "B")]
    by_name = {normalized(v["abbr"]): v for v in configured}
    events, matched, identities = [], set(), set()
    for path, documents in sorted(sources):
        if not isinstance(documents, list):
            raise TypeError(f"Invalid YAML list: {path}")
        for document in documents:
            title = normalized(document.get("title", ""))
            target = ALIASES.get(title)
            key = normalized(target) if target else title
            # FSE in the security directory denotes Fast Software Encryption, not software engineering.
            if title == "fse" and "/SC/" in f"/{path}":
                key = normalized("FSE (Crypto)")
            venue = by_name.get(key) or by_name.get(title)
            if not venue:
                continue
            for edition in document.get("confs", []):
                year = edition.get("year")
                if not isinstance(year, int) or not now.year <= year <= now.year + 3:
                    continue
                timeline = edition.get("timeline") or [{"deadline": None}]
                for index, item in enumerate(timeline):
                    label = str(item.get("comment") or f"第 {index + 1} 轮")
                    zone = str(item.get("timezone") or edition.get("timezone") or "")
                    raw = item.get("deadline")
                    abstract = item.get("abstract_deadline")
                    identity = f"{venue['abbr']}:{year}:{edition.get('id', year)}:{index + 1}"
                    uid = hashlib.sha256(identity.encode()).hexdigest()[:24]
                    if uid in identities:
                        raise ValueError(f"Duplicate deadline identity: {identity}")
                    identities.add(uid)
                    matched.add(venue["abbr"])
                    events.append({
                        "id": uid, "venue": venue["abbr"], "venue_name": venue["name"],
                        "level": venue["ccf_level"], "area": venue["ccf_area"], "year": year,
                        "round": label, "deadline": str(raw) if raw is not None else None,
                        "deadline_utc": deadline_utc(raw, zone),
                        "abstract_deadline": str(abstract) if abstract is not None else None,
                        "abstract_deadline_utc": deadline_utc(abstract, zone), "timezone": zone,
                        "conference_dates": str(edition.get("date") or ""), "place": str(edition.get("place") or ""),
                        "link": safe_url(edition.get("link")), "source_url": f"{SOURCE}/blob/main/{path}",
                    })
    events.sort(key=lambda e: (e["deadline_utc"] or "9999", e["venue"], e["id"]))
    return {
        "version": 1, "catalog_edition": "CCF 2026 第七版",
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {"name": "CCF Deadlines / CCFDDL", "url": SOURCE, "archive_sha256": archive_sha256,
                   "license": "MIT", "note": "社区汇总，非逐条官网核验；投稿前请确认会议官网。"},
        "coverage": {"configured_conferences": len(configured), "matched_conferences": len(matched),
                     "missing_venues": sorted(v["abbr"] for v in configured if v["abbr"] not in matched)},
        "events": events,
    }


def read_archive(body):
    import yaml
    sources = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for info in archive.infolist():
            parts = info.filename.split("/", 1)
            if len(parts) != 2 or not re.fullmatch(r"conference/[A-Za-z]+/[A-Za-z0-9_.+-]+\.ya?ml", parts[1]):
                continue
            total += info.file_size
            if info.file_size > 256 * 1024 or total > 16 * 1024 * 1024:
                raise ValueError("Upstream YAML archive exceeds limits")
            sources.append((parts[1], yaml.safe_load(archive.read(info))))
        license_names = [n for n in archive.namelist() if n.count("/") == 1 and n.endswith("/LICENSE")]
        if len(license_names) != 1:
            raise ValueError("Missing upstream license")
        license_text = archive.read(license_names[0]).decode("utf-8")
    if not sources:
        raise ValueError("No conference data in upstream archive")
    return sources, license_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use a previously downloaded upstream archive")
    parser.add_argument("--output", type=Path, default=ROOT / "frontend/static/deadlines.json")
    parser.add_argument("--keep-existing-on-error", action="store_true")
    args = parser.parse_args()
    try:
        if args.archive:
            body = args.archive.read_bytes()
        else:
            with urlopen(Request(ARCHIVE, headers={"User-Agent": "LitHub-Pavilion-deadlines/1"}), timeout=60) as response:
                body = response.read(MAX_ARCHIVE + 1)
        if len(body) > MAX_ARCHIVE:
            raise ValueError("Upstream archive exceeds size limit")
        sources, license_text = read_archive(body)
        with (ROOT / "seeds/venues.csv").open(encoding="utf-8-sig", newline="") as stream:
            venues = list(csv.DictReader(stream))
        feed = build_feed(venues, sources, datetime.now(timezone.utc), hashlib.sha256(body).hexdigest())
        if len(feed["events"]) < 50:
            raise ValueError("Unexpectedly small upstream feed; preserving the previous snapshot")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        licenses = args.output.parent / "data-sources"
        licenses.mkdir(exist_ok=True)
        (licenses / "CCFDDL-LICENSE.txt").write_text(license_text, encoding="utf-8")
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(feed, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(args.output)
        print(json.dumps({"events": len(feed["events"]), **feed["coverage"]}, ensure_ascii=False))
    except Exception as error:
        if args.keep_existing_on_error and args.output.is_file():
            print(f"WARNING: keeping the dated deadline snapshot: {type(error).__name__}: {error}", file=sys.stderr)
        else:
            raise


if __name__ == "__main__":
    main()
