"""ORM 模型（对应设计方案 5.2 表结构）。时间戳一律 ISO8601 UTC 文本。"""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    abbr: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    dblp_stream: Mapped[str] = mapped_column(Text, unique=True)
    dblp_toc_pattern: Mapped[str | None] = mapped_column(Text)
    issn: Mapped[str | None] = mapped_column(Text, unique=True)
    openalex_source_id: Mapped[str | None] = mapped_column(Text, unique=True)
    s2_venue: Mapped[str | None] = mapped_column(Text)  # S2 bulk 兜底过滤用的 venue 名（如 ICLR）
    type: Mapped[str] = mapped_column(Text)  # conf | journal
    ccf_level: Mapped[str] = mapped_column(Text)
    ccf_area: Mapped[str] = mapped_column(Text, default="人工智能")
    active: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        CheckConstraint("type IN ('conf','journal')", name="ck_venues_type"),
        CheckConstraint("ccf_level IN ('A','B')", name="ck_venues_level"),
    )


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dblp_key: Mapped[str | None] = mapped_column(Text, unique=True)
    dblp_mdate: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="dblp")
    openalex_id: Mapped[str | None] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    title_norm: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"))
    venue = relationship("Venue", lazy="joined")
    year: Mapped[int] = mapped_column(Integer)
    ccf_level: Mapped[str] = mapped_column(Text)
    ccf_area: Mapped[str] = mapped_column(Text, default="人工智能")
    doi: Mapped[str | None] = mapped_column(Text, unique=True)
    arxiv_id: Mapped[str | None] = mapped_column(Text, unique=True)
    s2_id: Mapped[str | None] = mapped_column(Text, unique=True)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    pdf_status: Mapped[str] = mapped_column(Text, default="pending")
    pdf_path: Mapped[str | None] = mapped_column(Text)
    pdf_source: Mapped[str | None] = mapped_column(Text)
    official_url: Mapped[str] = mapped_column(Text)
    oa_url: Mapped[str | None] = mapped_column(Text)
    venue_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    publication_date: Mapped[str | None] = mapped_column(Text)
    enriched_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, default=utcnow_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=utcnow_iso, onupdate=utcnow_iso)

    __table_args__ = (
        CheckConstraint(
            "source IN ('dblp','openalex','manual') AND ("
            "(source='dblp' AND dblp_key IS NOT NULL) OR "
            "(source='openalex' AND openalex_id IS NOT NULL) OR "
            "(source='manual' AND (doi IS NOT NULL OR arxiv_id IS NOT NULL)))",
            name="ck_papers_source",
        ),
        CheckConstraint("pdf_status IN ('pending','downloaded','failed','closed')", name="ck_papers_pdf_status"),
        CheckConstraint("ccf_level IN ('A','B')", name="ck_papers_level"),
        CheckConstraint(
            "pdf_source IS NULL OR pdf_source IN ('arxiv','neurips','pmlr','openreview','anthology','cvf','aaai','ijcai','jmlr','other_oa')",
            name="ck_papers_pdf_source",
        ),
        CheckConstraint("year BETWEEN 2000 AND 2100", name="ck_papers_year"),
        Index("ix_papers_venue_year", "venue_id", "year"),
        Index("ix_papers_year", "year"),
        Index("ix_papers_title_norm", "title_norm"),
        Index("ix_papers_created_at", "created_at"),
        Index("ix_papers_pdf_pending", "pdf_status", sqlite_where=text("pdf_status='pending'")),
    )


class Direction(Base):
    __tablename__ = "directions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    min_score: Mapped[float] = mapped_column(Float, default=2.0)
    enabled: Mapped[int] = mapped_column(Integer, default=1)


class DirectionRule(Base):
    __tablename__ = "direction_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    direction_id: Mapped[int] = mapped_column(ForeignKey("directions.id", ondelete="CASCADE"))
    keyword: Mapped[str] = mapped_column(Text)
    field: Mapped[str] = mapped_column(Text, default="both")
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    enabled: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        CheckConstraint("field IN ('title','abstract','both')", name="ck_rules_field"),
        Index("ix_rules_direction_enabled", "direction_id", "enabled"),
    )


class PaperDirection(Base):
    __tablename__ = "paper_directions"

    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True)
    direction_id: Mapped[int] = mapped_column(ForeignKey("directions.id", ondelete="CASCADE"), primary_key=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(Text, default="rule")
    created_at: Mapped[str] = mapped_column(Text, default=utcnow_iso)

    __table_args__ = (CheckConstraint("source IN ('rule','manual')", name="ck_pd_source"),)


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text, unique=True)


class PaperAuthor(Base):
    __tablename__ = "paper_authors"

    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True)
    author_order: Mapped[int] = mapped_column(Integer)


class CrawlLog(Base):
    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(Text)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id"))
    status: Mapped[str] = mapped_column(Text)
    papers_new: Mapped[int] = mapped_column(Integer, default=0)
    papers_updated: Mapped[int] = mapped_column(Integer, default=0)
    pdf_downloaded: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[str] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)  # running 中为 NULL

    __table_args__ = (
        CheckConstraint(
            "task_type IN ('weekly','backfill','pdf_backlog','reclassify','monthly')", name="ck_logs_task"
        ),
        CheckConstraint("status IN ('running','success','partial','failed')", name="ck_logs_status"),
        Index("ix_logs_task_started", "task_type", "started_at"),
    )


class CrawlState(Base):
    __tablename__ = "crawl_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(Text, unique=True)
    cursor: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text, default=utcnow_iso, onupdate=utcnow_iso)


class PdfWhitelist(Base):
    __tablename__ = "pdf_whitelist"

    host: Mapped[str] = mapped_column(Text, primary_key=True)
    owner: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[int] = mapped_column(Integer, default=1)


FTS_DDL = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
        title, abstract,
        content='papers', content_rowid='id',
        tokenize='porter unicode61'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS papers_fts_ai AFTER INSERT ON papers BEGIN
      INSERT INTO papers_fts(rowid, title, abstract)
      VALUES (new.id, new.title, coalesce(new.abstract, ''));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS papers_fts_au AFTER UPDATE ON papers BEGIN
      INSERT INTO papers_fts(papers_fts, rowid, title, abstract)
      VALUES ('delete', old.id, old.title, coalesce(old.abstract, ''));
      INSERT INTO papers_fts(rowid, title, abstract)
      VALUES (new.id, new.title, coalesce(new.abstract, ''));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS papers_fts_ad AFTER DELETE ON papers BEGIN
      INSERT INTO papers_fts(papers_fts, rowid, title, abstract)
      VALUES ('delete', old.id, old.title, coalesce(old.abstract, ''));
    END
    """,
]
