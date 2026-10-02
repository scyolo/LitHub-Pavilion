"""Safe bootstrap regressions on temporary databases only."""
from pathlib import Path

from sqlalchemy.orm import Session

from app.bootstrap import initialize_database
from app.config import PROJECT_ROOT
from app.models import Direction, Venue


def test_empty_database_is_ready_and_repeat_start_preserves_edits(engine, seed_venue_abbrs):
    initialize_database(engine, PROJECT_ROOT / "seeds")
    with Session(engine) as session:
        assert {abbr for abbr, in session.query(Venue.abbr)} == seed_venue_abbrs
        assert session.query(Direction).count() == 16
        venue = session.query(Venue).filter(Venue.abbr == "ICLR").one()
        venue.openalex_source_id = "S123456"
        venue.active = 0
        session.commit()
    initialize_database(engine, PROJECT_ROOT / "seeds")
    with Session(engine) as session:
        assert {abbr for abbr, in session.query(Venue.abbr)} == seed_venue_abbrs
        venue = session.query(Venue).filter(Venue.abbr == "ICLR").one()
        assert venue.openalex_source_id == "S123456"
        assert venue.active == 0
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM papers_fts").scalar() == 0
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_default_paths_do_not_depend_on_cwd(tmp_path, monkeypatch):
    from app.config import BACKEND_ROOT, Settings

    monkeypatch.chdir(tmp_path)
    config = Settings(_env_file=None)
    assert str(BACKEND_ROOT).replace("\\", "/") in config.database_url
    assert Path(config.seeds_dir).is_absolute()
    assert Path(config.snapshot_dir).is_absolute()
    assert Path(config.snapshot_state_file).is_absolute()

def test_legacy_publisher_identity_migration_preserves_ids_links_and_fts(tmp_path):
    from sqlalchemy.schema import CreateTable
    from app.db import _make_engine
    from app.migrations import migrate_publisher_identity
    from app.models import Base, FTS_DDL, Paper, PaperDirection
    import re

    engine = _make_engine('sqlite:///' + (tmp_path / 'legacy.db').as_posix())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            ddl = str(CreateTable(table).compile(engine))
            if table.name == 'papers':
                ddl = re.sub(r'\s*publisher_key TEXT,', '', ddl)
                ddl = re.sub(r',?\s*UNIQUE \(publisher_key\)', '', ddl)
                ddl = ddl.replace(' OR publisher_key IS NOT NULL', '')
            conn.exec_driver_sql(ddl)
        for statement in FTS_DDL:
            conn.exec_driver_sql(statement)
    with Session(engine) as session:
        v = Venue(abbr='TEST', name='Test', dblp_stream='conf/test', type='conf', ccf_level='A')
        d = Direction(code='test', name='Test')
        session.add_all([v, d]); session.flush()
        # Use SQL: the ORM intentionally already knows the new optional column.
        session.connection().exec_driver_sql("INSERT INTO papers(id,source,dblp_key,title,title_norm,venue_id,year,ccf_level,ccf_area,citation_count,pdf_status,official_url,venue_confirmed,created_at,updated_at) VALUES(7,'dblp','conf/test/key','Test model','test model',?,2024,'A','AI',0,'closed','https://example.org',1,'2024-01-01','2024-01-01')", (v.id,))
        session.add(PaperDirection(paper_id=7, direction_id=d.id, source='manual', score=9))
        session.commit()
    migrate_publisher_identity(engine)
    with Session(engine) as session:
        p = session.get(Paper, 7)
        assert p.title == 'Test model' and p.publisher_key is None
        assert session.query(PaperDirection).one().source == 'manual'
        p.publisher_key = 'https://example.org/article'
        p.source = 'manual'; p.dblp_key = None
        session.commit()
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT rowid FROM papers_fts WHERE papers_fts MATCH 'model'").scalar() == 7
        assert conn.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert conn.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
    engine.dispose()
