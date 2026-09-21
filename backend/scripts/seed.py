"""Add missing seed records without overwriting mappings or disabling user configuration."""
from app.bootstrap import seed_missing
from app.config import settings
from app.db import get_session


def main():
    with get_session() as session:
        seed_missing(session, settings.seeds_dir)
    print("Missing seed records added; existing settings preserved.")


if __name__ == "__main__":
    main()
