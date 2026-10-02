import sqlite3

import pytest
from sqlalchemy import create_engine

from app.migrations import migrate_author_slots


def legacy(tmp_path, duplicate_order=False):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as db:
        db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE papers (id INTEGER PRIMARY KEY);
        CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE paper_authors (
          paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
          author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
          author_order INTEGER NOT NULL, PRIMARY KEY(paper_id, author_id));
        CREATE INDEX author_lookup ON paper_authors(author_id);
        INSERT INTO papers VALUES(1);
        INSERT INTO authors VALUES(10,'Same Name'),(11,'Another');
        INSERT INTO paper_authors VALUES(1,10,1),(1,11,2);
        ''')
        if duplicate_order:
            db.execute('UPDATE paper_authors SET author_order=1')
    return path, create_engine('sqlite:///' + path.as_posix())


def test_migration_preserves_rows_and_supports_duplicate_author_slots(tmp_path):
    path, engine = legacy(tmp_path)
    migrate_author_slots(engine)
    migrate_author_slots(engine)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        assert db.execute('SELECT paper_id,author_id,author_order FROM paper_authors ORDER BY author_order').fetchall() == [(1,10,1),(1,11,2)]
        db.execute("INSERT INTO paper_authors(paper_id,author_id,author_order) VALUES(1,10,3)")
        assert db.execute('SELECT count(*) FROM paper_authors').fetchone()[0] == 3
        assert db.execute("SELECT name FROM sqlite_master WHERE name='author_lookup'").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO paper_authors(paper_id,author_id,author_order) VALUES(1,11,3)')
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        db.execute('DELETE FROM papers WHERE id=1')
        assert db.execute('SELECT count(*) FROM paper_authors').fetchone()[0] == 0
    engine.dispose()


def test_ambiguous_legacy_order_rejected_without_changing_schema_or_rows(tmp_path):
    path, engine = legacy(tmp_path, duplicate_order=True)
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT sql FROM sqlite_master WHERE name='paper_authors'").fetchone()[0]
    with pytest.raises(RuntimeError, match='order'):
        migrate_author_slots(engine)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT sql FROM sqlite_master WHERE name='paper_authors'").fetchone()[0] == before
        assert db.execute('SELECT count(*) FROM paper_authors').fetchone()[0] == 2
    engine.dispose()
