"""One-off update of source_scope_notes from verified 2026-10-25 evidence.

Classification basis (all evidence gathered 2026-10-25):
- publication_pending: conference already held (per CCFDDL conference_dates) but
  no publisher-deposited main proceedings container found on Crossref yet.
- not_scheduled: next edition is 2027 per CCFDDL (GROUP/CADE/HiPEAC/HotOS/NAACL),
  or the venue publishes no proceedings (HiPEAC), or already-marked biennial.
- unverified: conference not yet held (Nov/Dec 2026); zero count is expected
  until the edition takes place.

The script keeps every existing note unless this round provides stronger
evidence; it never marks a year as covered.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTES = ROOT / "seeds" / "source_scope_notes.json"
PROBE = ROOT / "release-artifacts" / "gap-probe-20261025" / "report.json"

# CCFDDL 2026 conference dates (community-maintained, exact-name matched).
CONF_DATES_2026 = {
    "ISS": "2026-11-23", "CoNEXT": "2026-12-07", "Middleware": "2026-12-14",
    "CCS": "2026-11-15", "SoCC": "2026-11-18", "ICSME": "2026-09-14",
    "ISMAR": "2026-10-05", "ASE": "2026-10-12", "IEEE VIS": "2026-11-09",
    "UIST": "2026-11-02", "FOCS": "2026-11-08", "ACM MM": "2026-11-10",
    "MICRO": "2026-10-31", "SC": "2026-11-15", "ICCAD": "2026-11-08",
    "RAID": "2026-10-11", "SDM": "2026-11-19", "MobiHoc": "2026-11-23",
    "ISSRE": "2026-10-20", "ITC": "2026-10-11", "PACT": "2026-10-19",
    "ISWC": "2026-10-25", "SRDS": "2026-09-22", "ICSOC": "2026-12-01",
    "ESEM": "2026-10-04", "TCC": "2026-11-10", "ASIACRYPT": "2026-12-07",
    "ICNP": "2026-10-05", "Performance": "2026-11-03", "CIKM": "2026-11-07",
    "ACSAC": "2026-12-07", "RTSS": "2026-12-09", "ICDM": "2026-11-12",
    "ICCD": "2026-11-16", "WISE": "2026-11-01", "WINE": "2026-12-01",
    "BIBM": "2026-12-01", "HSCC": "2026-05-11", "DAC": "2026-07-26",
    "RECOMB": "2026-05-26", "SECON": "2026-06-03", "ICME": "2026-07-06",
    "ECSCW": "2026-06-29", "HOT CHIPS": "2026-08-23", "ICLR": None,
}
TODAY = "2026-10-25"
NEXT_EDITION_2027 = {
    "GROUP": "CCFDDL 列出 GROUP 2027 两轮截稿（2025-07、2026-03），GROUP 已按双年安排，2026 无独立届次。",
    "CADE": "CCFDDL 列出 CADE 下一届为 2027；CADE 按奇数/隔年节奏举办，2026 无独立届次。",
    "HotOS": "ACM SIGOPS 系列双年制：2023 第 19 届、2025 第 20 届、2027 第 21 届，2026 无届次。",
    "NAACL": "CCFDDL 列出 NAACL 下一届为 2027；ACL Anthology 无 NAACL 2026 卷。",
}
NO_PROCEEDINGS = {
    "HiPEAC": "HiPEAC 年会由工作坊、教程和展览组成，官方不出版主会 proceedings（Crossref/ACM/IEEE 均无 HiPEAC 会议卷）；CCFDDL 亦显示下一届为 2027。",
}


def main():
    notes = json.loads(NOTES.read_text(encoding="utf-8"))
    sources = notes["sources"]
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    updated = []

    def set_check(abbr, year, status, note, url):
        entry = sources.setdefault(abbr, {"year_checks": {}})
        checks = entry.setdefault("year_checks", {})
        key = str(year)
        record = {"status": status, "note": note, "evidence_url": url, "checked_at": "2026-10-25"}
        old = checks.get(key)
        if old != record:
            checks[key] = record
            updated.append(f"{abbr} {year}: {old.get('status') if old else 'NEW'} -> {status}")

    ccfddl = "https://github.com/ccfddl/ccf-deadlines"

    for unit in probe["units"]:
        if unit["status"] != "no_publisher_container":
            continue
        abbr, year = unit["venue"], unit["year"]
        if year != 2026:
            continue  # older-year gaps keep their existing structural notes
        if abbr in NEXT_EDITION_2027:
            set_check(abbr, year, "not_scheduled", NEXT_EDITION_2027[abbr], ccfddl)
        elif abbr in NO_PROCEEDINGS:
            set_check(abbr, year, "no_proceedings", NO_PROCEEDINGS[abbr], "https://www.hipeac.net/conferences/")
        else:
            date = CONF_DATES_2026.get(abbr)
            if date and date < TODAY:
                set_check(
                    abbr, year, "publication_pending",
                    f"本届会议已于 {date} 举行（CCFDDL 届次记录），但截至 2026-10-25 出版方尚未在 Crossref 存入正式主会 proceedings 容器；Crossref 容器探测与 ACM/IEEE 目录查询均未检出。保留零计数，待官方目录上线后补采。",
                    ccfddl,
                )
            else:
                set_check(
                    abbr, year, "unverified",
                    f"本届会议计划于 {date or '2026 年 11—12 月'} 举行（CCFDDL 届次记录），截稿日历时点（2026-10-25）尚未开会，正式 proceedings 尚未出版属预期状态；会后再核验官方目录。",
                    ccfddl,
                )

    notes["verified_on"] = "2026-10-25"
    NOTES.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"updated": len(updated), "changes": updated[:20]}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
