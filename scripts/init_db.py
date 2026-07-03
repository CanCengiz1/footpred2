"""Bootstrap the database: run all Alembic migrations to head.

Usage: python scripts/init_db.py
DB URL via FOOTPRED_DB env var (default sqlite:///footpred.db).
"""
from alembic import command
from alembic.config import Config


def main() -> None:
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    print("Database schema is up to date.")


if __name__ == "__main__":
    main()
