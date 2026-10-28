"""Build the independent industry report catalog from curated seed metadata.

The feed indexes public technical reports, system cards and model papers from
major industrial labs. It deliberately stays outside the CCF A/B paper ledger:
no records are imported into the database or the snapshot.

Run from the project root:
    python backend/scripts/build_industry_data.py
    python backend/scripts/build_industry_data.py --verify-arxiv
"""
from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ORGS = ROOT / "seeds/industry_orgs.csv"
DEFAULT_REPORTS = ROOT / "seeds/industry_reports.csv"
DEFAULT_OUTPUT = ROOT / "frontend/static/industry.json"

SCHEMA_VERSION = 1
FEED_TITLE = "大厂技术报告"
SOURCE_NOTE = "公开技术报告、系统卡与模型论文的独立索引；仅收录元数据与官方链接，不镜像全文，也不计入 CCF A/B 论文库统计。"
KINDS = {
    "tech_report": "技术报告",
    "system_card": "系统卡",
    "model_card": "模型卡",
    "paper": "研究论文",
    "journal_article": "期刊论文",
    "blog": "官方博客",
    "code_release": "代码与权重",
}
ORG_COLUMNS = ("code", "name", "name_en", "country", "note")
REPORT_COLUMNS = ("id", "org", "title", "kind", "year", "published", "url", "arxiv_id", "summary", "tags")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ARXIV_ID = re.compile(r"\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}")
_ORG_CODE = re.compile(r"[a-z0-9][a-z0-9-]{1,19}")
_REPORT_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,80}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _read_rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(columns):
            raise ValueError(f"{path.name} columns must be {','.join(columns)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path.name} is empty")
    return rows


def _text(value: str | None, label: str, *, minimum: int = 1, maximum: int = 200) -> str:
    text = (value or "").strip()
    if not minimum <= len(text) <= maximum or _CONTROL.search(text) or "<" in text or ">" in text:
        raise ValueError(f"Invalid {label}")
    return text


def _safe_url(value: str | None) -> str:
    text = (value or "").strip()
    if not text or re.search(r"[\s\\\x00-\x1f<>\"']", text):
        raise ValueError(f"Invalid URL: {text[:80]}")
    url = urlparse(text)
    host = (url.hostname or "").lower().rstrip(".")
    if url.scheme != "https" or not host or url.username or url.password or "." not in host:
        raise ValueError(f"URL must be public HTTPS: {text[:80]}")
    if host.endswith((".local", ".localhost", ".localdomain")):
        raise ValueError(f"URL host is not public: {text[:80]}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError(f"URL host is not public: {text[:80]}")
    return text


def _published(value: str | None, year: int) -> str:
    text = (value or "").strip()
    if not _DATE.fullmatch(text):
        raise ValueError(f"Invalid publication date: {text!r}")
    parsed = date.fromisoformat(text)
    if parsed.year != year:
        raise ValueError(f"Publication date {text} does not match year {year}")
    return text


def load_orgs(path: Path = DEFAULT_ORGS) -> list[dict]:
    orgs = []
    codes = set()
    for row in _read_rows(path, ORG_COLUMNS):
        code = (row["code"] or "").strip()
        if not _ORG_CODE.fullmatch(code) or code in codes:
            raise ValueError(f"Invalid or duplicate organization code: {code!r}")
        orgs.append({
            "code": code,
            "name": _text(row["name"], "organization name", maximum=60),
            "name_en": _text(row["name_en"], "organization English name", maximum=80),
            "country": _text(row["country"], "organization country", maximum=20),
            "note": _text(row["note"], "organization note", maximum=120),
        })
        codes.add(code)
    return orgs


def load_reports(path: Path = DEFAULT_REPORTS, org_codes: set[str] | None = None) -> list[dict]:
    reports = []
    ids = set()
    titles = set()
    for row in _read_rows(path, REPORT_COLUMNS):
        report_id = (row["id"] or "").strip()
        if not _REPORT_ID.fullmatch(report_id) or report_id in ids:
            raise ValueError(f"Invalid or duplicate report id: {report_id!r}")
        org = (row["org"] or "").strip()
        if org_codes is not None and org not in org_codes:
            raise ValueError(f"Unknown organization: {org!r}")
        title = _text(row["title"], "report title", minimum=3, maximum=300)
        normalized_title = unicodedata.normalize("NFKC", title).casefold()
        if normalized_title in titles:
            raise ValueError(f"Duplicate report title: {title!r}")
        kind = (row["kind"] or "").strip()
        if kind not in KINDS:
            raise ValueError(f"Unknown report kind: {kind!r}")
        year_text = (row["year"] or "").strip()
        if not year_text.isdigit() or not 2000 <= int(year_text) <= 2100:
            raise ValueError(f"Invalid report year: {year_text!r}")
        year = int(year_text)
        published = _published(row["published"], year)
        url = _safe_url(row["url"])
        arxiv_id = (row["arxiv_id"] or "").strip() or None
        if arxiv_id is not None:
            if not _ARXIV_ID.fullmatch(arxiv_id):
                raise ValueError(f"Invalid arXiv id: {arxiv_id!r}")
            if url != f"https://arxiv.org/abs/{arxiv_id}":
                raise ValueError(f"arXiv report URL must be canonical: {report_id}")
        summary = _text(row["summary"], "report summary", minimum=10, maximum=180)
        tags = [tag.strip() for tag in (row["tags"] or "").split(";") if tag.strip()]
        if not 1 <= len(tags) <= 6 or len(set(tags)) != len(tags) or any(len(tag) > 24 for tag in tags):
            raise ValueError(f"Invalid report tags: {report_id}")
        reports.append({
            "id": report_id, "org": org, "title": title, "kind": kind, "year": year,
            "published": published, "url": url, "arxiv_id": arxiv_id,
            "summary": summary, "tags": tags,
        })
        ids.add(report_id)
        titles.add(normalized_title)
    return reports


def _utc_timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("generated_at must include a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_feed(orgs: list[dict], reports: list[dict], *, generated_at: str | None = None) -> dict:
    counts = Counter(report["org"] for report in reports)
    unused = [org["code"] for org in orgs if not counts.get(org["code"])]
    if unused:
        raise ValueError(f"Organizations without reports: {', '.join(unused)}")
    known = {org["code"] for org in orgs}
    unknown = sorted(set(counts) - known)
    if unknown:
        raise ValueError(f"Reports reference unknown organizations: {', '.join(unknown)}")

    org_rows = sorted(
        ({**org, "count": counts[org["code"]]} for org in orgs),
        key=lambda org: (-org["count"], org["code"]),
    )
    ordered = sorted(reports, key=lambda report: (report["published"], report["id"]), reverse=True)
    kind_counts = Counter(report["kind"] for report in reports)
    year_counts = Counter(report["year"] for report in reports)
    return {
        "schema_version": SCHEMA_VERSION,
        "title": FEED_TITLE,
        "generated_at": _utc_timestamp(generated_at),
        "source_note": SOURCE_NOTE,
        "orgs": org_rows,
        "reports": ordered,
        "stats": {
            "reports": len(ordered),
            "orgs": len(org_rows),
            "by_kind": {kind: kind_counts[kind] for kind in KINDS if kind_counts[kind]},
            "by_year": {str(year): year_counts[year] for year in sorted(year_counts)},
            "latest": max(report["published"] for report in ordered),
        },
    }


def write_feed(feed: dict, output: Path = DEFAULT_OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(feed, ensure_ascii=False, sort_keys=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(output)


def _normalized_title(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", ascii_text.casefold())


def _arxiv_xml(ids: list[str]) -> bytes:
    query = urllib.parse.urlencode({"id_list": ",".join(ids), "max_results": len(ids)})
    request = urllib.request.Request(
        f"https://export.arxiv.org/api/query?{query}",
        headers={"User-Agent": "LitHub-Pavilion/1.0 (metadata verification)"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def verify_arxiv(reports: list[dict], *, sleep=time.sleep) -> list[str]:
    targets = [report for report in reports if report["arxiv_id"]]
    mismatches = []
    namespace = {"a": "http://www.w3.org/2005/Atom"}
    for start in range(0, len(targets), 10):
        batch = targets[start:start + 10]
        for attempt in range(3):
            try:
                root = ET.fromstring(_arxiv_xml([report["arxiv_id"] for report in batch]))
                break
            except Exception as exc:  # noqa: BLE001 - network errors are reported after retries
                if attempt == 2:
                    raise RuntimeError(f"arXiv API unavailable: {exc}") from exc
                sleep(5 * (attempt + 1))
        returned = {}
        for entry in root.findall("a:entry", namespace):
            identifier = entry.find("a:id", namespace).text.rsplit("/abs/", 1)[-1]
            returned[re.sub(r"v\d+$", "", identifier)] = entry.find("a:title", namespace).text
        for report in batch:
            title = returned.get(report["arxiv_id"])
            if title is None:
                mismatches.append(f"{report['id']}: arXiv id {report['arxiv_id']} was not returned")
            elif _normalized_title(title) != _normalized_title(report["title"]):
                mismatches.append(f"{report['id']}: expected {report['title']!r}, got {title!r}")
        if start + 10 < len(targets):
            sleep(3)
    return mismatches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orgs", type=Path, default=DEFAULT_ORGS)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--generated-at", help="ISO 8601 timestamp for reproducible builds")
    parser.add_argument("--verify-arxiv", action="store_true", help="check every arXiv id and title online")
    args = parser.parse_args(argv)
    try:
        orgs = load_orgs(args.orgs)
        reports = load_reports(args.reports, {org["code"] for org in orgs})
        if args.verify_arxiv:
            mismatches = verify_arxiv(reports)
            if mismatches:
                print("\n".join(mismatches), file=sys.stderr)
                return 1
        feed = build_feed(orgs, reports, generated_at=args.generated_at)
        write_feed(feed, args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "reports": feed["stats"]["reports"],
        "orgs": feed["stats"]["orgs"],
        "by_kind": feed["stats"]["by_kind"],
        "latest": feed["stats"]["latest"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
