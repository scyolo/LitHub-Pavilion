"""数据库引擎与会话。SQLite 连接即设 PRAGMA（6.3 调优项），全部业务 SQL 经 ORM/参数绑定。"""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_engine: Engine | None = None
_SessionLocal = None


def _make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        db_path = make_url(database_url).database
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 15},
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return engine
    return create_engine(database_url, pool_pre_ping=True)


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _make_engine(settings.database_url)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def get_db():
    """FastAPI 依赖：请求级会话。"""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def db_file_path() -> Path | None:
    url = settings.database_url
    if not url.startswith("sqlite"):
        return None
    path = make_url(url).database
    return Path(path) if path and path != ":memory:" else None
