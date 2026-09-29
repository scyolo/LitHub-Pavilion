"""Small, backed-up SQLite migrations. Never use writable_schema or drop data."""
import re


def migrate_publisher_identity(engine):
    """Rebuild the legacy CHECK atomically so DOI-less proceedings get real IDs.

    Caller takes a verified backup first. Existing row ids, user indexes,
    triggers and foreign-key references survive; unexpected schemas fail shut.
    """
    raw = engine.raw_connection()
    connection = raw.driver_connection
    try:
        ddl = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='papers'").fetchone()[0]
        needle = "doi IS NOT NULL OR arxiv_id IS NOT NULL"
        if needle not in ddl or "publisher_key" in ddl:
            raise RuntimeError("Unsupported papers identity CHECK; migrate explicitly")
        schema = connection.execute("SELECT sql FROM sqlite_master WHERE tbl_name='papers' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        columns = [row[1] for row in connection.execute("PRAGMA table_info(papers)")]
        quoted = ",".join('"' + name.replace('"', '""') + '"' for name in columns)
        updated, count = re.subn(r'(?i)CREATE TABLE\s+["`\[]?papers["`\]]?\s*\(', 'CREATE TABLE papers_identity_migration (publisher_key TEXT UNIQUE, ', ddl, count=1)
        if count != 1:
            raise RuntimeError("Unrecognized papers table DDL")
        updated = updated.replace(needle, needle + " OR publisher_key IS NOT NULL")
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        original_count = connection.execute("SELECT count(*) FROM papers").fetchone()[0]
        connection.execute(updated)
        connection.execute(f"INSERT INTO papers_identity_migration ({quoted}) SELECT {quoted} FROM papers")
        connection.execute("DROP TABLE papers")
        connection.execute("ALTER TABLE papers_identity_migration RENAME TO papers")
        for (statement,) in schema:
            connection.execute(statement)
        if connection.execute("SELECT count(*) FROM papers").fetchone()[0] != original_count:
            raise RuntimeError("Migration changed paper count")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Migration foreign key check failed")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Migration integrity check failed")
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='papers_fts'").fetchone():
            connection.execute("INSERT INTO papers_fts(papers_fts, rank) VALUES('integrity-check', 1)")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
        raw.close()
