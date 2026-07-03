"""Read model for the ML layer (CQRS-lite).

The ML pipeline consumes one flat, read-optimized frame of completed matches
with odds pivoted wide — it never walks entity repositories. Both
implementations delegate to the same pivot helper so they cannot diverge.

Canonical frame columns:
  match_id, league_key, league, country, match_date, kickoff_utc,
  ht_home, ht_away, ft_home, ft_away, has_ht,
  odds_<market>_<selection>_<bookmaker>   (float, NaN when unquoted;
                                           '.' in market names -> '_',
                                           e.g. odds_ou_2_5_over_bet365)
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Protocol, Tuple

import pandas as pd

from footpred.domain.entities import League, Match, OddsQuote


class MatchOddsReader(Protocol):
    def load_completed(self) -> pd.DataFrame: ...


def odds_col(market: str, selection: str, bookmaker: str) -> str:
    return f"odds_{market.replace('.', '_')}_{selection}_{bookmaker}"


def frame_from_records(
    matches: Iterable[Match],
    odds: Iterable[OddsQuote],
    leagues: Iterable[League],
) -> pd.DataFrame:
    """Shared pivot: domain records -> canonical flat frame."""
    league_by_id = {l.id: l for l in leagues}
    rows = []
    for m in matches:
        lg = league_by_id.get(m.league_id)
        rows.append({
            "match_id": m.id,
            "league_key": lg.canonical_key if lg else str(m.league_id),
            "league": lg.name if lg else str(m.league_id),
            "country": lg.country if lg else None,
            "match_date": m.match_date,
            "kickoff_utc": m.kickoff_utc,
            "ht_home": m.ht_home, "ht_away": m.ht_away,
            "ft_home": m.ft_home, "ft_away": m.ft_away,
            "has_ht": m.has_halftime(),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    quotes = pd.DataFrame(
        [{"match_id": q.match_id,
          "col": odds_col(q.market, q.selection, q.bookmaker),
          "price": q.decimal_odds} for q in odds]
    )
    if not quotes.empty:
        wide = quotes.pivot_table(index="match_id", columns="col",
                                  values="price", aggfunc="first")
        frame = frame.merge(wide, on="match_id", how="left")
    return frame.sort_values("match_id").reset_index(drop=True)


class InMemoryMatchOddsReader:
    """Reads from an InMemoryUnitOfWork (tests)."""

    def __init__(self, uow) -> None:
        self._uow = uow

    def load_completed(self) -> pd.DataFrame:
        matches = [m for m in self._uow.matches._items
                   if m.ft_home is not None and m.ft_away is not None]
        return frame_from_records(matches, self._uow.odds.items,
                                  self._uow.leagues.all())


class SqlMatchOddsReader:
    """Reads from the SQL database via the existing UoW mappers, then
    delegates to the shared pivot. Row volumes here are small (tens of
    thousands); a hand-tuned SQL pivot is a Postgres-era optimization."""

    def __init__(self, session_factory) -> None:
        self._factory = session_factory

    def load_completed(self) -> pd.DataFrame:
        from sqlalchemy import select

        from footpred.infra.db import models as m
        from footpred.infra.db.uow import _league, _match

        with self._factory() as s:
            matches = [_match(r) for r in s.scalars(
                select(m.MatchRow).where(m.MatchRow.ft_home.is_not(None),
                                         m.MatchRow.ft_away.is_not(None)))]
            leagues = [_league(r) for r in s.scalars(select(m.LeagueRow))]
            odds_rows: List[Tuple] = s.execute(
                select(m.OddsRow.match_id, m.OddsRow.bookmaker, m.OddsRow.market,
                       m.OddsRow.selection, m.OddsRow.decimal_odds)
            ).all()
        odds = [OddsQuote(id=None, match_id=r[0], bookmaker=r[1], market=r[2],
                          selection=r[3], decimal_odds=r[4]) for r in odds_rows]
        return frame_from_records(matches, odds, leagues)
