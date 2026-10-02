"""Import the printed CCF directory, preserving configured identifiers and mappings.

Maintenance only: python scripts/import_ccf_catalog.py --pdf CCF-2026.pdf --source-url URL
Requires PyMuPDF for table extraction; the running app never needs a PDF library.
This does not collect papers or claim publication coverage.
"""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AREAS = [
    "计算机体系结构/并行与分布计算/存储系统", "计算机网络", "网络与信息安全",
    "软件工程/系统软件/程序设计语言", "数据库/数据挖掘/内容检索", "计算机科学理论",
    "计算机图形学与多媒体", "人工智能", "人机交互与普适计算", "交叉/综合/新兴",
]
# Identity, not abbreviation alone: FSE is two unrelated conferences.
DISPLAY_NAMES = {
    ("journal", "TCC"): "TCC Journal", ("journal", "ASE"): "ASE Journal",
    ("journal", "RE"): "RE Journal", ("journal", "CC"): "CC Journal",
    ("journal", "CSCW"): "CSCW Journal", ("journal", "AAMAS"): "JAAMAS",
    ("journal", "WWW"): "WWW Journal",
}
ISSNS = {"JASA": "0001-4966", "JSLHR": "1092-4388", "Cognition": "0010-0277"}


def extract_rows(pdf):
    import fitz
    result = []
    area = kind = level = None
    with fitz.open(pdf) as document:
        for index, page in enumerate(document):
            text = page.get_text()
            compact = re.sub(r"\s+", "", text)
            if "中国计算机学会推荐国际学术期刊" in text:
                kind = "journal"
            elif "中国计算机学会推荐国际学术会议" in text and index:
                kind = "conf"
            area = next((value for value in AREAS if value in compact), area)
            for heading, value in (("一、A类", "A"), ("二、B类", "B"), ("三、C类", "C")):
                if heading in compact:
                    level = value
            if kind and level in ("A", "B"):
                for table in page.find_tables().tables:
                    for row in table.extract():
                        if row[0] and re.fullmatch(r"\d+", row[0].strip()):
                            result.append({"page": index + 1, "area": area, "type": kind,
                                           "level": level, "cells": [" ".join((v or "").split()) for v in row]})
    return result


def merge_catalog(rows, existing):
    fields = list(existing[0])
    venues = {v["abbr"]: dict(v) for v in existing}
    evidence = {}
    consumed = set()
    for row in rows:
        _, printed, name, _, url = row["cells"]
        abbr = re.sub(r"（原.*?）", "", printed).strip() or name
        name = re.sub(r"（原.*?）", "", name).strip()
        abbr = abbr.replace("CODES+ ISSS", "CODES+ISSS")
        stream_match = re.search(r"/db/((?:conf|journals)/[^/\s]+)", url.replace(" ", ""))
        stream = stream_match[1] if stream_match else ""
        if abbr == "FSE" and stream == "conf/fse":
            abbr = "FSE (Crypto)"
        abbr = DISPLAY_NAMES.get((row["type"], abbr), abbr)
        if name == "Computational Linguistics":
            abbr, stream = "CL", "journals/coling"
        # Printed-directory links can contain legacy names and typos.
        if abbr == "PR":
            stream = "journals/pr"
        if abbr == "AAMAS" and row["type"] == "conf":
            stream = "conf/amas"
        if abbr == "BCRA":
            stream = "journals/bcra"
        old = next((v for v in existing if v["type"] == row["type"] and
                    (v["abbr"] == abbr or (stream and v["dblp_stream"] == stream))), None)
        if old:
            abbr = old["abbr"]
            consumed.add(abbr)
        if abbr in evidence:
            prior = evidence[abbr]
            if (prior["type"], prior["level"], prior["dblp_stream"]) != (row["type"], row["level"], stream):
                raise ValueError(f"Ambiguous catalogue identity: {abbr}")
            prior["areas"].append(row["area"])
            prior["pages"].append(row["page"])
            continue
        value = venues.get(abbr) or dict.fromkeys(fields, "")
        value.update(abbr=abbr, name=old["name"] if old else name, type=row["type"],
                     ccf_level=row["level"], ccf_area=old["ccf_area"] if old and abbr == "TOMM" else row["area"],
                     active=old["active"] if old else "1")
        value["dblp_stream"] = old["dblp_stream"] if old and abbr != "CL" else stream
        if abbr in ISSNS:
            value["issn"] = value["issn"] or ISSNS[abbr]
        if not old and row["type"] == "conf":
            # Generic stream/year enumeration, not a guessed TOC filename.
            value["s2_venue"] = abbr
        venues[abbr] = value
        evidence[abbr] = {"type": row["type"], "level": row["level"], "areas": [row["area"]],
                          "pages": [row["page"]], "printed_abbr": printed, "printed_url": url,
                          "dblp_stream": value["dblp_stream"]}
    if consumed != {v["abbr"] for v in existing}:
        raise ValueError("Existing sources are absent from the new directory; review manually")
    counts = Counter((v["ccf_level"], v["type"]) for v in venues.values())
    if counts != {("A", "conf"): 58, ("B", "conf"): 132, ("A", "journal"): 37, ("B", "journal"): 111}:
        raise ValueError(f"Unexpected 2026 directory counts: {counts}")
    streams = [v["dblp_stream"] for v in venues.values() if v["dblp_stream"]]
    if len(streams) != len(set(streams)):
        raise ValueError("Duplicate publication stream")
    return list(venues.values()), evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--checked-at", required=True, help="Actual verification date, YYYY-MM-DD")
    parser.add_argument("--seeds", type=Path, default=ROOT / "seeds")
    args = parser.parse_args()
    with (args.seeds / "venues.csv").open(encoding="utf-8-sig", newline="") as stream:
        existing = list(csv.DictReader(stream))
    rows = extract_rows(args.pdf)
    venues, evidence = merge_catalog(rows, existing)
    provenance = {"edition": "CCF 2026 第七版", "checked_at": args.checked_at,
                  "source": args.source_url, "source_sha256": hashlib.sha256(args.pdf.read_bytes()).hexdigest(),
                  "listed_entries": len(rows), "unique_venues": len(venues),
                  "note": "TOMM、DKE 跨领域重复列出，各保留一个来源及全部领域证据。FSE 等同名来源按身份区分。来源配置不代表已有论文或完整覆盖。",
                  "venues": evidence}
    with (args.seeds / "venues.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(existing[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(venues)
    (args.seeds / "ccf_catalog_provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"venues": len(venues), "directory_entries": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
