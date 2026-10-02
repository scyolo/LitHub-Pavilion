"""Read-only publication/coverage audit. Never treats a complete index as complete CCF coverage.

Reparse saved official metadata and compare every identity with the live database.
Crossref is supplemental: an exhausted DOI inventory does not prove that every
accepted article has a DOI. FTS integrity is checked on an in-memory copy only.
"""
import argparse
import asyncio
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.cleaning import is_noise_title, normalize_title
from app.collectors.crossref import identify_venue, item_to_raw
from app.collectors import publisher_toc as toc
from app.collectors.editions import joint_edition, publication_schedule
from app.config import settings
from app.db import db_file_path


def latest_entries(directory, pattern, array, key):
    """Keep the most recent attempt for each unit, including a recent failure."""
    result = {}
    for path in sorted(directory.glob(pattern)):
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        for entry in report.get(array, []):
            identity = key(entry)
            if identity is not None:
                result[identity] = {**entry, "report_file": str(path.resolve()),
                                    "collected_at": report.get("finished_at") or report.get("started_at")}
    return result


def official_records(entry, directory):
    def read(url):
        return (directory / ("toc-" + hashlib.sha256(url.encode()).hexdigest()[:16] + ".txt")).read_text("utf-8")
    abbr, year, url = entry["venue"], entry["year"], entry["url"]
    body = read(url)
    if abbr == "SIGKDD":
        from app.collectors.kdd import CATALOGUES, parse_kdd_research
        if CATALOGUES.get(year) != url:
            raise ValueError("Unverified KDD catalogue URL")
        return parse_kdd_research(body, year)
    if abbr in ("AAAI", "ICAPS", "JAIR"):
        from app.collectors.ojs import fetch_ojs_inventory
        async def cached_read(address):
            return read(address)
        return asyncio.run(fetch_ojs_inventory(cached_read, abbr, year))
    if abbr == "TPAMI":
        from app.collectors.csdl import fetch_csdl_inventory
        async def cached_csdl(address):
            return read(address)
        return asyncio.run(fetch_csdl_inventory(cached_csdl, year))
    if abbr == "ICLR": return toc.parse_iclr(body, year)
    if abbr == "ICML" and url.startswith("https://icml.cc/static/virtual/data/"): return toc.parse_icml(body, year)
    if abbr == "AAMAS": return toc.parse_aamas(body, year)
    if abbr == "IJCAI": return toc.parse_ijcai(body, year)
    if abbr == "KR": return toc.parse_kr(body, year)
    if abbr == "ECCV" and url.startswith("https://eccv.ecva.net/static/virtual/data/"): return toc.parse_eccv_catalogue(body, year)
    if abbr == "ECCV": return toc.parse_eccv(body, year)
    if abbr == "NeurIPS":
        volumes = toc.neurips_main_volumes(body, year)
        return [p for volume in volumes for p in toc.parse_neurips(read(volume), year)] if volumes else toc.parse_neurips(body, year)
    if abbr in ("CVPR", "ICCV"): return toc.parse_cvf(body, year, abbr)
    if abbr == "JMLR": return toc.parse_jmlr(body, year)
    if abbr in ("ICML", "UAI", "COLT"): return toc.parse_pmlr(body, year, url, abbr)
    if abbr in ("ACL", "EMNLP", "COLING", "TACL", "CL"):
        return toc.parse_anthology(body, year, abbr, url.rsplit("/", 1)[1][:-4])
    raise ValueError("Unknown official inventory adapter")


def build_audit(path, reports_dir, years, *, baseline=None, check_fts=True):
    path, reports_dir = path.resolve(), reports_dir.resolve()
    today = datetime.now(timezone.utc).date()
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")  # one consistent read snapshot
        def rows(sql, values=()): return [dict(r) for r in connection.execute(sql, values)]
        papers = rows("SELECT id,venue_id,title,title_norm,year,ccf_level,doi,arxiv_id,oa_url,publisher_key,publication_date,venue_confirmed,note,abstract IS NOT NULL AND trim(abstract)!='' AS has_abstract FROM papers")
        venues = {v["id"]: v for v in rows("SELECT * FROM venues")}
        active = {v["abbr"]: SimpleNamespace(**v) for v in venues.values() if v["active"] and v["ccf_level"] in ("A", "B")}
        by_publisher = {p["publisher_key"]: p for p in papers if p["publisher_key"]}
        by_doi = {p["doi"]: p for p in papers if p["doi"]}
        grouped = defaultdict(list)
        for paper in papers: grouped[(paper["venue_id"], paper["year"])].append(paper)
        evidence = lambda p: bool(p["publisher_key"] or "Verified publisher metadata: Crossref DOI " in (p["note"] or ""))
        arxiv = lambda p: bool(p["arxiv_id"] or "arxiv.org/" in (p["oa_url"] or "").lower() or (p["doi"] or "").startswith("10.48550/arxiv."))
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "database": str(path), "read_only": True, "pdf_downloads": 0,
            "scope": {"configured_active_ab_venues": len(active), "years": list(years), "all_ccf_areas": False},
            "full_collection_verified": False,
            "paper_count": len(papers),
            "levels": dict(Counter(p["ccf_level"] for p in papers)),
            "publisher_evidence_papers": sum(evidence(p) for p in papers),
            "papers_without_publisher_evidence": sum(not evidence(p) for p in papers),
            "venue_unconfirmed": sum(not p["venue_confirmed"] for p in papers),
            "arxiv_associated_papers": sum(arxiv(p) for p in papers),
            "arxiv_with_publisher_evidence": sum(arxiv(p) and evidence(p) for p in papers),
            "arxiv_link_without_unique_id": sum(arxiv(p) and not p["arxiv_id"] for p in papers),
            "without_abstract": sum(not p["has_abstract"] for p in papers),
            "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
            "foreign_key_errors": [list(r) for r in connection.execute("PRAGMA foreign_key_check")],
            "identifier_duplicates": {}, "date_issues": [], "coverage": [], "crossref_sources": [],
        }
        for field in ("doi", "arxiv_id", "dblp_key", "openalex_id", "s2_id", "publisher_key"):
            report["identifier_duplicates"][field] = rows(f"SELECT {field} AS identifier, count(*) AS n FROM papers WHERE {field} IS NOT NULL GROUP BY {field} HAVING count(*)>1")
        for p in papers:
            value = p["publication_date"]
            if not value: continue
            try: parsed = date.fromisoformat(value)
            except (ValueError, TypeError): reason = "invalid_date"
            else:
                reason = "year_mismatch" if parsed.year != p["year"] else ("future_indexed_date" if parsed > today else None)
            if reason: report["date_issues"].append({"id": p["id"], "year": p["year"], "publication_date": value, "reason": reason})
        report["date_issue_counts"] = dict(Counter(r["reason"] for r in report["date_issues"]))
        report["venue_level_mismatches"] = [p["id"] for p in papers if p["ccf_level"] != venues[p["venue_id"]]["ccf_level"]]
        report["title_collision_candidates"] = rows("SELECT venue_id,title_norm,count(*) AS n,group_concat(id) AS ids,group_concat(year) AS years FROM papers GROUP BY venue_id,title_norm HAVING count(*)>1 ORDER BY n DESC,venue_id,title_norm")
        report["title_collision_group_count"] = len(report["title_collision_candidates"])
        report["title_collision_note"] = "Candidates, NOT proven duplicates. Distinct DOI/author/version identities must not be merged by title alone."
        report["unresolved_catalogue_dois"] = [p["id"] for p in papers if "Unresolved DOI reported by official catalogue:" in (p["note"] or "")]
        report["directions"] = rows("SELECT d.code,d.name,d.enabled,count(pd.paper_id) AS paper_count FROM directions d LEFT JOIN paper_directions pd ON pd.direction_id=d.id GROUP BY d.id ORDER BY d.id")
        report["manual_tag_count"] = connection.execute("SELECT count(*) FROM paper_directions WHERE source='manual'").fetchone()[0]
        report["active_rule_count"] = connection.execute("SELECT count(*) FROM direction_rules WHERE enabled=1").fetchone()[0]
        report["without_direction"] = connection.execute("SELECT count(*) FROM papers p WHERE NOT EXISTS (SELECT 1 FROM paper_directions pd JOIN directions d ON d.id=pd.direction_id WHERE pd.paper_id=p.id AND d.enabled=1)").fetchone()[0]
        report["without_direction_note"] = "The nine configured topics are not an exhaustive taxonomy; unmatched papers remain searchable and are not automatically mislabeled."
        official = latest_entries(reports_dir, "official-inventory-*.json", "units", lambda e: (e.get("venue"), e.get("year")) if e.get("year") else None)
        assessments = latest_entries(reports_dir, "inventory-assessment-*.json", "units", lambda e: (e.get("venue"), e.get("year")))
        expected_dois = defaultdict(set)
        expected_titles = defaultdict(dict)
        doi_sources = defaultdict(set)
        for prefix, entry in latest_entries(reports_dir, "publisher-repair-*.json", "prefixes", lambda e: e["prefix"]).items():
            source = {k: entry.get(k) for k in ("prefix", "records", "inventory_complete", "error", "report_file", "collected_at")}
            report["crossref_sources"].append(source)
            cache = Path(entry.get("cache", ""))
            if not cache.is_file():
                source["audit_error"] = "Metadata cache unavailable"
                continue
            for line in cache.read_text("utf-8").splitlines():
                if not line: continue
                item = json.loads(line)
                venue = identify_venue(item, active)
                raw = item_to_raw(item) if venue else None
                if raw and raw.year in years and not is_noise_title(normalize_title(raw.title)):
                    unit = (venue.abbr, raw.year)
                    expected_dois[unit].add(raw.doi)
                    expected_titles[unit][raw.doi] = raw.title
                    doi_sources[unit].add(prefix)
        for abbr, venue in active.items():
            for year in years:
                unit = (abbr, year)
                current = grouped[(venue.id, year)]
                item = {"venue": abbr, "level": venue.ccf_level, "year": year, "stored": len(current),
                        "publisher_evidence": sum(evidence(p) for p in current),
                        "arxiv_associated": sum(arxiv(p) for p in current),
                        "status": "not_verified", "open_year": year >= today.year}
                expected = expected_dois[unit]
                missing = sorted(doi for doi in expected if doi not in by_doi or by_doi[doi]["venue_id"] != venue.id)
                year_mismatches = [
                    {"id": by_doi[doi]["id"], "doi": doi, "crossref_year": year,
                     "stored_year": by_doi[doi]["year"], "official_inventory": bool(by_doi[doi]["publisher_key"])}
                    for doi in sorted(expected) if doi in by_doi and by_doi[doi]["venue_id"] == venue.id and by_doi[doi]["year"] != year
                ]
                title_mismatches = [
                    {"id": by_doi[doi]["id"], "doi": doi, "stored_title": by_doi[doi]["title"], "crossref_title": title}
                    for doi, title in sorted(expected_titles[unit].items())
                    if doi in by_doi and by_doi[doi]["title_norm"] != normalize_title(title)
                ]
                item.update(crossref_expected=len(expected), crossref_linked=len(expected)-len(missing), crossref_missing=missing,
                            crossref_title_mismatches=title_mismatches, crossref_year_mismatches=year_mismatches, crossref_sources=sorted(doi_sources[unit]))
                if expected: item["status"] = "crossref_only_not_full_coverage"
                entry = official.get(unit)
                schedule = publication_schedule(abbr, year)
                item["schedule"] = schedule
                if entry:
                    item["official_source"] = {k: entry.get(k) for k in ("url", "inventory_complete", "records", "status", "reason", "error", "report_file", "collected_at")}
                    if entry.get("inventory_complete"):
                        try:
                            records = official_records(entry, reports_dir)
                            if len(records) != entry["records"]:
                                raise ValueError("Saved inventory size changed since report")
                            absent, mismatched, title_mismatches = [], [], []
                            for raw in records:
                                key = raw.extra["publisher_key"]
                                p = by_publisher.get(key)
                                if p is None:
                                    absent.append(key)
                                elif p["venue_id"] != venue.id or p["year"] != year:
                                    mismatched.append({"id": p["id"], "publisher_key": key, "stored_year": p["year"], "reason": "venue/year mismatch"})
                                elif p["title_norm"] != normalize_title(raw.title):
                                    title_mismatches.append({"id": p["id"], "publisher_key": key,
                                                             "stored_title": p["title"], "official_title": raw.title})
                            identity_linked = len(records) - len(absent) - len(mismatched)
                            item.update(official_expected=len(records), official_identity_linked=identity_linked,
                                        official_linked=identity_linked-len(title_mismatches), official_missing=absent,
                                        official_mismatches=mismatched, official_title_mismatches=title_mismatches)
                            if absent or mismatched:
                                item["status"] = "official_import_incomplete"
                            elif title_mismatches:
                                # A spelling/source-title difference is not a missing paper,
                                # but still must not be silently counted as exact agreement.
                                item["status"] = "official_inventory_title_differences"
                            else:
                                item["status"] = "official_inventory_matched"
                        except (ValueError, OSError) as exc:
                            item["official_audit_error"] = str(exc)
                            item["status"] = "official_cache_unverified"
                    elif entry.get("status"):
                        item["status"] = entry["status"]
                    elif not expected:
                        item["status"] = "official_unavailable"
                elif schedule["status"] != "scheduled":
                    item["status"] = "not_scheduled_by_adapter" if schedule["status"] == "not_applicable" else schedule["status"]
                edition = joint_edition(abbr, year)
                if edition:
                    canonical = active.get(edition["canonical_venue"])
                    item["joint_edition"] = {**edition, "canonical_stored": len(grouped[(canonical.id, year)]) if canonical else 0}
                    item["status"] = "joint_edition_requires_review" if grouped[(venue.id, year)] else "joint_edition"
                assessment = assessments.get(unit)
                if assessment:
                    item["source_assessment"] = assessment
                    if item["status"] in ("not_verified", "official_unavailable") and assessment.get("status") == "official_program_only":
                        item["status"] = "official_program_only"
                report["coverage"].append(item)
        schedule_by_unit = {(v.id, y): publication_schedule(v.abbr, y) for v in active.values() for y in years}
        not_applicable = {unit for unit, decision in schedule_by_unit.items() if decision["status"] == "not_applicable"}
        report["not_applicable_year_records"] = [
            {"id": p["id"], "venue": venues[p["venue_id"]]["abbr"], "year": p["year"],
             "title": p["title"], "venue_confirmed": p["venue_confirmed"], "doi": p["doi"]}
            for p in papers if (p["venue_id"], p["year"]) in not_applicable]
        report["not_applicable_year_record_count"] = len(report["not_applicable_year_records"])
        # Off-cycle records remain review candidates; never silently correct a year.
        report["unscheduled_year_records"] = report["not_applicable_year_records"]
        report["unscheduled_year_record_count"] = len(report["unscheduled_year_records"])
        report["outside_configured_years"] = [
            {"id": p["id"], "venue": venues[p["venue_id"]]["abbr"], "year": p["year"], "title": p["title"]}
            for p in papers if p["year"] not in years]
        report["unscheduled_year_note"] = "Off-cycle conference years are represented as not_applicable; no year is auto-corrected from a DBLP-key suffix or an arXiv date."
        report["crossref_identity_missing_count"] = sum(len(u["crossref_missing"]) for u in report["coverage"])
        report["crossref_title_mismatch_count"] = sum(len(u["crossref_title_mismatches"]) for u in report["coverage"])
        report["crossref_year_mismatch_count"] = sum(len(u["crossref_year_mismatches"]) for u in report["coverage"])
        report["crossref_year_note"] = "A DOI present in a different year is a date disagreement, not a missing identity; verified publisher issue years take precedence over stale Crossref dates."
        report["crossref_title_note"] = "Crossref title differences are review candidates, not automatic errors: official proceedings titles may take precedence. Never overwrite author/identity conflicts by DOI alone."
        report["coverage_status_counts"] = dict(Counter(u["status"] for u in report["coverage"]))
        report["coverage_note"] = "Matched means all items in the retrieved official inventory are linked as of collection, not a promise about unpublished/future proceedings. Crossref and secondary-index completeness are not global completeness."
        if baseline:
            with sqlite3.connect(baseline.resolve().as_uri() + "?mode=ro", uri=True) as old:
                old_papers = {r[0]: r[1:] for r in old.execute("SELECT id,year,title FROM papers")}
                surviving = [p for p in papers if p["id"] in old_papers]
                report["baseline_comparison"] = {
                    "baseline": str(baseline.resolve()), "paper_count": len(old_papers),
                    "net_paper_increase": len(papers)-len(old_papers),
                    "surviving_ids_with_year_corrected": sum(old_papers[p["id"]][0] != p["year"] for p in surviving),
                    "surviving_ids_with_title_corrected": sum(old_papers[p["id"]][1] != p["title"] for p in surviving),
                    "old_ids_no_longer_present": len(old_papers) - len(surviving),
                    "manual_tag_count": old.execute("SELECT count(*) FROM paper_directions WHERE source='manual'").fetchone()[0],
                }
        if check_fts:
            # FTS5 integrity-check is syntactically an INSERT; run it only on
            # a disposable in-memory backup, never on the audited file.
            with sqlite3.connect(":memory:") as copy:
                connection.backup(copy)
                report["fts_indexes_checked"] = []
                for index in ("papers_fts", "paper_titles_fts"):
                    copy.execute(f"INSERT INTO {index}({index}, rank) VALUES('integrity-check', 1)")
                    report["fts_indexes_checked"].append(index)
                report["fts_integrity"] = "ok (read-only source, checked on memory copy)"
        else: report["fts_integrity"] = "not_checked"
        return report
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=db_file_path())
    parser.add_argument("--reports", type=Path, default=Path("artifacts") / ("publication-audit-" + datetime.now(timezone.utc).strftime("%Y%m%d")))
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--year-from", type=int, default=settings.startup_year_from)
    parser.add_argument("--year-to", type=int, default=settings.startup_years[-1])
    parser.add_argument("--skip-fts", action="store_true")
    args = parser.parse_args()
    if not args.database or not args.database.is_file(): parser.error("An existing database is required")
    if not 2000 <= args.year_from <= args.year_to <= 2100: parser.error("Invalid year range")
    report = build_audit(args.database, args.reports, range(args.year_from, args.year_to+1), baseline=args.baseline, check_fts=not args.skip_fts)
    args.reports.mkdir(parents=True, exist_ok=True)
    target = args.reports / ("final-audit-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(target.resolve()), **{k: report[k] for k in ("paper_count", "publisher_evidence_papers", "arxiv_with_publisher_evidence", "without_direction", "date_issue_counts", "crossref_identity_missing_count", "crossref_title_mismatch_count", "coverage_status_counts", "quick_check", "fts_integrity", "full_collection_verified")}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
