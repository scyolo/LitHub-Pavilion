"""Rebuild the external-content index atomically, preserving tables and triggers."""
from app.db import get_engine
from app.models import FTS_DDL


def main():
    with get_engine().begin() as connection:
        for statement in FTS_DDL:
            connection.exec_driver_sql(statement)
        connection.exec_driver_sql("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")
        connection.exec_driver_sql("INSERT INTO papers_fts(papers_fts, rank) VALUES('integrity-check', 1)")
        connection.exec_driver_sql("INSERT INTO paper_titles_fts(paper_titles_fts) VALUES('rebuild')")
        connection.exec_driver_sql("INSERT INTO paper_titles_fts(paper_titles_fts, rank) VALUES('integrity-check', 1)")
    print("FTS5 rebuilt and verified against paper contents.")


if __name__ == "__main__":
    main()
