"""Initialize an empty database or safely complete missing seed records."""
from app.bootstrap import initialize_database
from app.db import get_engine


def main():
    initialize_database(get_engine())
    print("Database and FTS5 ready; existing paper data preserved.")


if __name__ == "__main__":
    main()
