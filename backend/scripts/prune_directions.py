"""Remove out-of-scope directions and reassign/delete papers for the 2026-11-04 coverage reset.

Run with: python -m scripts.prune_directions   (from backend/, PYTHONPATH=.)
Add --apply to write; default is a dry run.
After applying, run python -m scripts.reindex_topics --database PATH to retag
the retained papers with the current keyword rules and venue priors.
"""
import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "data" / "papers.db"

DROP_DIRECTIONS = ["speech", "bioinformatics"]

# Venues removed from scope entirely: papers deleted, venue deactivated.
DROP_VENUES = [
    # speech / audio / acoustics
    "JASA", "INTER- SPEECH", "TASLP", "JSLHR", "SPECOM", "ICASSP",
    # bioinformatics / medical informatics
    "BIBM", "PLOS Computational Biology", "Bioinformatics",
    "Briefings in Bioinformatics", "TCBB", "JAMIA", "RECOMB",
    # remote sensing / transportation / cognitive science
    "TGARS", "TITS", "CogSci", "Cognition",
    # control / evolutionary computation / hybrid systems
    "TSMC", "AEI", "TFS", "TEC", "PPSN", "Evolutionary Computation", "HSCC",
    # non-research proceedings
    "Proc. IEEE",
    # general science / cross-disciplinary
    "SCIS", "The Computer Journal", "FCS", "JCST",
]

# Venues kept and given a direction mapping so their papers are classified.
MAP_VENUES = {
    "TKDE": ["retrieval", "graph"],
    "WWW": ["retrieval", "graph"],
    "Information Sciences": ["ml", "retrieval"],
    "IPM": ["retrieval"],
    "KAIS": ["retrieval", "graph"],
    "DASFAA": ["retrieval", "graph"],
    "DKE": ["retrieval", "graph"],
    "WISE": ["retrieval"],
    "JASIST": ["retrieval"],
    "TWEB": ["retrieval"],
    "TODS": ["retrieval"],
    "GeoInformatica": ["retrieval"],
    "ICWSM": ["hci", "retrieval"],
    "TAP": ["hci"],
    "BCRA": ["security"],
    "DCC": ["multimodal"],
    "TCSVT": ["cv", "multimodal"],
    "SIIMS": ["cv"],
    "IEEE Transactions on Cybernetics": ["ml"],
    "EJIS": ["hci"],
    "ICMR": ["cv", "multimodal", "retrieval"],
    "IS": ["retrieval"],
    "WWW Journal": ["retrieval", "graph"],
    "DSE": ["retrieval", "graph"],
}


def fingerprint(conn):
    cur = conn.cursor()
    out = {}
    out["papers"] = cur.execute("select count(*) from papers").fetchone()[0]
    out["directions"] = cur.execute("select count(*) from directions").fetchone()[0]
    out["paper_directions"] = cur.execute("select count(*) from paper_directions").fetchone()[0]
    out["untagged"] = cur.execute(
        "select count(*) from papers where id not in (select paper_id from paper_directions)"
    ).fetchone()[0]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--database", type=Path, default=DB)
    args = ap.parse_args()

    database = args.database.resolve()
    if not database.is_file():
        ap.error("An existing SQLite database is required")
    mode = "rw" if args.apply else "ro"
    conn = sqlite3.connect(database.as_uri() + f"?mode={mode}", uri=True)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    before = fingerprint(conn)
    print("before:", json.dumps(before, ensure_ascii=False))

    # --- resolve ids ---
    drop_dir_ids = [r[0] for r in cur.execute(
        "select id from directions where code in (%s)" % ",".join("?" * len(DROP_DIRECTIONS)),
        DROP_DIRECTIONS).fetchall()]
    print("dropping direction ids:", drop_dir_ids)

    venue_rows = {r[1]: r[0] for r in cur.execute("select id, abbr from venues").fetchall()}
    missing = [v for v in DROP_VENUES + list(MAP_VENUES) if v not in venue_rows]
    if missing:
        raise SystemExit(f"Unknown venue abbr: {missing}")

    drop_venue_ids = [venue_rows[v] for v in DROP_VENUES]
    paper_ids = [r[0] for r in cur.execute(
        "select id from papers where venue_id in (%s)" % ",".join("?" * len(drop_venue_ids)),
        drop_venue_ids).fetchall()]
    print(f"papers to delete: {len(paper_ids)}")

    if not args.apply:
        print("\n[dry run] pass --apply to write changes")
        conn.close()
        return

    # --- delete papers (children first; FKs cascade but be explicit) ---
    CHUNK = 500
    deleted = 0
    for i in range(0, len(paper_ids), CHUNK):
        batch = paper_ids[i:i + CHUNK]
        marks = ",".join("?" * len(batch))
        cur.execute(f"delete from paper_directions where paper_id in ({marks})", batch)
        cur.execute(f"delete from paper_authors where paper_id in ({marks})", batch)
        cur.execute(f"delete from paper_conferences where paper_id in ({marks})", batch)
        cur.execute(f"delete from papers where id in ({marks})", batch)
        deleted += len(batch)
    print("papers deleted:", deleted)

    # --- remove the two directions + their rules/venue priors ---
    marks = ",".join("?" * len(drop_dir_ids))
    cur.execute(f"delete from paper_directions where direction_id in ({marks})", drop_dir_ids)
    cur.execute(f"delete from direction_rules where direction_id in ({marks})", drop_dir_ids)
    cur.execute(f"delete from direction_venues where direction_id in ({marks})", drop_dir_ids)
    cur.execute(f"delete from directions where id in ({marks})", drop_dir_ids)

    # --- deactivate dropped venues ---
    cur.execute("update venues set active=0 where id in (%s)" % ",".join("?" * len(drop_venue_ids)),
                drop_venue_ids)

    # --- add venue priors for kept venues ---
    added = 0
    for abbr, codes in MAP_VENUES.items():
        vid = venue_rows[abbr]
        for code in codes:
            row = cur.execute("select id from directions where code=?", (code,)).fetchone()
            if not row:
                raise SystemExit(f"missing direction {code}")
            exists = cur.execute(
                "select 1 from direction_venues where direction_id=? and venue_id=?",
                (row[0], vid)).fetchone()
            if not exists:
                cur.execute(
                    "insert into direction_venues(direction_id, venue_id, weight, enabled) values (?,?,1.0,1)",
                    (row[0], vid))
                added += 1
    print("venue priors added:", added)

    conn.commit()

    # --- rebuild search indexes; direction retagging uses scripts.reindex_topics ---
    conn.executescript("insert into papers_fts(papers_fts) values('rebuild');")
    conn.executescript("insert into paper_titles_fts(paper_titles_fts) values('rebuild');")
    conn.commit()
    after = fingerprint(conn)
    print("after:", json.dumps(after, ensure_ascii=False))
    conn.close()


if __name__ == "__main__":
    main()
