"""Safe bootstrap regressions on temporary databases only."""
from pathlib import Path

from sqlalchemy.orm import Session

from app.bootstrap import initialize_database
from app.config import PROJECT_ROOT
from app.models import Direction, Venue


def test_empty_database_is_ready_and_repeat_start_preserves_edits(engine):
    initialize_database(engine, PROJECT_ROOT / "seeds")
    with Session(engine) as session:
        assert session.query(Venue).count() == 28
        assert session.query(Direction).count() == 9
        venue = session.query(Venue).filter(Venue.abbr == "ICLR").one()
        venue.openalex_source_id = "S123456"
        venue.active = 0
        session.commit()
    initialize_database(engine, PROJECT_ROOT / "seeds")
    with Session(engine) as session:
        assert session.query(Venue).count() == 28
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
    assert Path(config.papers_root).is_absolute()
