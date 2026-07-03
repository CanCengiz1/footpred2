"""Engine and session factory.

DB URL comes from the FOOTPRED_DB env var; default is a local SQLite file.
Switching to PostgreSQL later is a URL change — nothing else.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "sqlite:///footpred.db"


def database_url() -> str:
    return os.environ.get("FOOTPRED_DB", DEFAULT_URL)


def make_engine(url: str | None = None):
    return create_engine(url or database_url(), future=True)


def make_session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(url), future=True, expire_on_commit=False)
