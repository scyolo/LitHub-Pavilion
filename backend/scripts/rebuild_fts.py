"""Rebuild the external-content index atomically, preserving tables and triggers."""
from app.db import get_engine


def main():
    with get_engine().begin() as connection:
        connection.exec_driver_sql("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")
        connection.exec_driver_sql("INSERT INTO papers_fts(papers_fts, rank) VALUES('integrity-check', 1)")
    print("FTS5 rebuilt and verified against paper contents.")


if __name__ == "__main__":
    main()
