"""Parity + integration tests: the SQL-backed UnitOfWork must behave
identically to the in-memory one for the generic odds-backfill
reconciliation the ingest pipeline depends on.

Every other test in this project runs against the in-memory UoW only (per
infra/memory.py's own docstring: "serve as the behavioural reference for the
SQLAlchemy implementation"). This is the first test in the suite to
construct a real SqlAlchemyUnitOfWork -- specifically to protect that
reference guarantee for the new existing_odds_for_match port method, which
would be easy to implement correctly on one side and subtly wrong on the
other without a test that actually exercises both.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from footpred.ingest.mapping import FOOTBALL_DATA_CO_UK
from footpred.infra.db.models import Base
from footpred.infra.db.uow import SqlAlchemyUnitOfWork
from footpred.infra.memory import InMemoryUnitOfWork
from footpred.services.import_service import ImportService

NARROW_ROW = {
    "Div": "E0", "Date": "17/08/2025", "HomeTeam": "Newcastle", "AwayTeam": "Fulham",
    "FTHG": 1, "FTAG": 0, "B365H": 1.9, "B365D": 3.4, "B365A": 4.2,
}
EXTENDED_ROW = {
    **NARROW_ROW,
    "AHh": -0.5, "B365AHH": 1.95, "B365AHA": 1.87,
    "B365CH": 1.85, "B365CD": 3.5, "B365CA": 4.4,
}


def _memory_uow_factory():
    uow = InMemoryUnitOfWork()
    return lambda: uow  # ImportService opens/closes the same instance each call


def _sql_uow_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/parity.db", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return lambda: SqlAlchemyUnitOfWork(factory)


def _run_backfill_scenario(uow_factory):
    """Import a narrow row, then a same-match extended row (adds Asian
    Handicap + closing 1x2) -- exactly the two-pass backfill scenario the
    pipeline's _reconcile_odds exists for. Returns both import reports and
    the final stored odds identity map for the one match."""
    service = ImportService(uow_factory)
    r1 = service.import_dataframe(pd.DataFrame([NARROW_ROW]), "narrow.csv", FOOTBALL_DATA_CO_UK)
    r2 = service.import_dataframe(pd.DataFrame([EXTENDED_ROW]), "extended.csv", FOOTBALL_DATA_CO_UK)

    with uow_factory() as uow:
        league = uow.leagues.get_by_key("E0")
        home = uow.teams.get_by_normalized("newcastle")
        away = uow.teams.get_by_normalized("fulham")
        siblings = uow.matches.find_by_pairing_date(
            league.id, home.id, away.id, date(2025, 8, 17))  # type: ignore[arg-type]
        assert len(siblings) == 1  # confirms this was backfill, not a second match
        odds = uow.odds.existing_odds_for_match(siblings[0].id)  # type: ignore[arg-type]
    return r1, r2, odds


def test_backfill_scenario_identical_across_sql_and_memory(tmp_path):
    _, r2_mem, odds_mem = _run_backfill_scenario(_memory_uow_factory())
    _, r2_sql, odds_sql = _run_backfill_scenario(_sql_uow_factory(tmp_path))

    assert odds_mem == odds_sql
    assert r2_mem.odds_quotes_backfilled == r2_sql.odds_quotes_backfilled
    # 1x2 closing (3) + AH opening (2) = 5 genuinely new quotes backfilled
    assert r2_mem.odds_quotes_backfilled == 5
    # the 3 original 1x2-opening quotes must still be there, untouched
    assert len(odds_mem) == 3 + 5


def test_sql_backend_persists_line_and_price_point(tmp_path):
    _, _, odds = _run_backfill_scenario(_sql_uow_factory(tmp_path))
    ah_home_key = next(k for k in odds if k[1] == "ah" and k[2] == "home")
    assert ah_home_key[3] == -0.5           # line
    assert ah_home_key[4] == "opening"      # price_point
    closing_1x2_key = next(k for k in odds if k[1] == "1x2" and k[4] == "closing")
    assert closing_1x2_key[3] is None       # 1x2 has no line
