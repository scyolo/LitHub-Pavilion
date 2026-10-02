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


def migrate_author_slots(engine):
    """Prepare slot-preserving authorship; caller must back up before use.

    Not wired into startup until ORM/import/export integration is completed.
    Existing author identities stay untouched. Position becomes the association
    identity; a display name and source identifier can later be stored per slot.
    """
    raw = engine.raw_connection()
    db = raw.driver_connection
    try:
        db.execute('BEGIN IMMEDIATE')
        columns = db.execute('PRAGMA table_info(paper_authors)').fetchall()
        names = [row[1] for row in columns]
        if set(names) == {'paper_id', 'author_id', 'author_order', 'display_name', 'source_author_id'}:
            pk = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
            if pk != ['paper_id', 'author_order']:
                raise RuntimeError('Unexpected author slot primary key')
            db.commit()
            return
        if set(names) != {'paper_id', 'author_id', 'author_order'}:
            raise RuntimeError('Unsupported legacy authorship schema')
        pk = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        if pk != ['paper_id', 'author_id']:
            raise RuntimeError('Unsupported legacy authorship primary key')
        if db.execute("SELECT 1 FROM paper_authors WHERE author_order IS NULL OR typeof(author_order)!='integer' OR author_order<1 LIMIT 1").fetchone():
            raise RuntimeError('Invalid legacy author order')
        if db.execute('SELECT 1 FROM paper_authors GROUP BY paper_id,author_order HAVING count(*)>1 LIMIT 1').fetchone():
            raise RuntimeError('Ambiguous legacy author order')
        # An external FK to this association needs a separately planned migration.
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            quoted = '"' + table.replace('"', '""') + '"'
            if any(row[2] == 'paper_authors' for row in db.execute('PRAGMA foreign_key_list(' + quoted + ')')):
                raise RuntimeError('External reference to authorship requires explicit migration')
        schema = db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='paper_authors' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        db.execute('''CREATE TABLE paper_author_slots_migration (
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
            author_order INTEGER NOT NULL CHECK(author_order >= 1),
            display_name TEXT,
            source_author_id TEXT,
            PRIMARY KEY (paper_id, author_order))''')
        db.execute('''INSERT INTO paper_author_slots_migration(paper_id,author_id,author_order)
                      SELECT paper_id,author_id,author_order FROM paper_authors''')
        fields = 'paper_id,author_id,author_order'
        for left, right in [('paper_authors', 'paper_author_slots_migration'), ('paper_author_slots_migration', 'paper_authors')]:
            if db.execute(f'SELECT {fields} FROM {left} EXCEPT SELECT {fields} FROM {right}').fetchone():
                raise RuntimeError('Author migration changed legacy rows')
        db.execute('DROP TABLE paper_authors')
        db.execute('ALTER TABLE paper_author_slots_migration RENAME TO paper_authors')
        for (statement,) in schema:
            db.execute(statement)
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Author slot foreign key check failed')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('Author slot integrity check failed')
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        raw.close()


def migrate_optional_dblp_stream(engine):
    """Some CCF A/B journals use ISSN instead of DBLP. Preserve their real identity.

    Caller takes a backup. Rebuild only the NOT NULL constraint; retain row IDs,
    all columns, indexes, triggers and foreign-key references in one transaction.
    """
    raw = engine.raw_connection()
    connection = raw.driver_connection
    try:
        ddl = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='venues'").fetchone()[0]
        updated, count = re.subn(r'(?i)(\b"?dblp_stream"?\s+\w+)\s+NOT\s+NULL', r'\1', ddl)
        if count != 1:
            raise RuntimeError("Unsupported venues DBLP constraint")
        updated, count = re.subn(r'(?i)CREATE TABLE\s+["`\[]?venues["`\]]?\s*\(', 'CREATE TABLE venues_optional_dblp (', updated, count=1)
        if count != 1:
            raise RuntimeError("Unsupported venues DDL")
        schema = connection.execute("SELECT sql FROM sqlite_master WHERE tbl_name='venues' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        columns = [row[1] for row in connection.execute("PRAGMA table_info(venues)")]
        quoted = ",".join('"' + name.replace('"', '""') + '"' for name in columns)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        before = connection.execute(f"SELECT {quoted} FROM venues ORDER BY id").fetchall()
        connection.execute(updated)
        connection.execute(f"INSERT INTO venues_optional_dblp ({quoted}) SELECT {quoted} FROM venues")
        connection.execute("DROP TABLE venues")
        connection.execute("ALTER TABLE venues_optional_dblp RENAME TO venues")
        for (statement,) in schema:
            connection.execute(statement)
        if connection.execute(f"SELECT {quoted} FROM venues ORDER BY id").fetchall() != before:
            raise RuntimeError("Venue migration changed existing records")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Venue migration foreign-key check failed")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Venue migration integrity check failed")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
        raw.close()
