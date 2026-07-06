"""SQLAlchemy implementation of the domain ports.

Repositories accept/return domain entities only — ORM rows never leak
upward. Behaviour must match infra.memory (the tested reference).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from footpred.domain.entities import (
    ImportRecord,
    League,
    Match,
    MatchSource,
    MatchStatus,
    OddsQuote,
    Team,
    TeamAlias,
)
from footpred.infra.db import models as m


# --- mappers ---------------------------------------------------------------

def _league(r: m.LeagueRow) -> League:
    return League(r.id, r.canonical_key, r.name, r.country)


def _team(r: m.TeamRow) -> Team:
    return Team(r.id, r.canonical_name, r.normalized_key)


def _alias(r: m.TeamAliasRow) -> TeamAlias:
    return TeamAlias(r.id, r.team_id, r.alias, r.normalized_alias, r.source, r.confidence)


def _match(r: m.MatchRow) -> Match:
    return Match(r.id, r.league_id, r.home_team_id, r.away_team_id, r.match_date,
                 r.kickoff_utc, r.ht_home, r.ht_away, r.ft_home, r.ft_away,
                 MatchStatus(r.status), r.import_id, r.dedupe_key)


# --- repositories ----------------------------------------------------------

class SqlLeagues:
    def __init__(self, s: Session):
        self._s = s

    def get_by_key(self, canonical_key: str) -> Optional[League]:
        r = self._s.scalar(select(m.LeagueRow).where(m.LeagueRow.canonical_key == canonical_key))
        return _league(r) if r else None

    def add(self, league: League) -> League:
        r = m.LeagueRow(canonical_key=league.canonical_key, name=league.name,
                        country=league.country)
        self._s.add(r)
        self._s.flush()
        league.id = r.id
        return league

    def all(self) -> List[League]:
        return [_league(r) for r in self._s.scalars(select(m.LeagueRow))]


class SqlTeams:
    def __init__(self, s: Session):
        self._s = s

    def get_by_normalized(self, normalized_key: str) -> Optional[Team]:
        r = self._s.scalar(select(m.TeamRow).where(m.TeamRow.normalized_key == normalized_key))
        return _team(r) if r else None

    def add(self, team: Team) -> Team:
        r = m.TeamRow(canonical_name=team.canonical_name, normalized_key=team.normalized_key)
        self._s.add(r)
        self._s.flush()
        team.id = r.id
        return team

    def all_normalized(self) -> Dict[str, int]:
        rows = self._s.execute(select(m.TeamRow.normalized_key, m.TeamRow.id)).all()
        return {k: i for k, i in rows}


class SqlAliases:
    def __init__(self, s: Session):
        self._s = s

    def get_by_normalized(self, normalized_alias: str) -> Optional[TeamAlias]:
        r = self._s.scalar(select(m.TeamAliasRow)
                           .where(m.TeamAliasRow.normalized_alias == normalized_alias))
        return _alias(r) if r else None

    def add(self, alias: TeamAlias) -> TeamAlias:
        r = m.TeamAliasRow(team_id=alias.team_id, alias=alias.alias,
                           normalized_alias=alias.normalized_alias,
                           source=alias.source, confidence=alias.confidence)
        self._s.add(r)
        self._s.flush()
        alias.id = r.id
        return alias


class SqlMatches:
    def __init__(self, s: Session):
        self._s = s

    def get_by_dedupe_key(self, key: str) -> Optional[Match]:
        r = self._s.scalar(select(m.MatchRow).where(m.MatchRow.dedupe_key == key))
        return _match(r) if r else None

    def find_by_pairing_date(self, league_id: int, home_team_id: int,
                             away_team_id: int, match_date: date) -> List[Match]:
        rows = self._s.scalars(select(m.MatchRow).where(
            m.MatchRow.league_id == league_id,
            m.MatchRow.home_team_id == home_team_id,
            m.MatchRow.away_team_id == away_team_id,
            m.MatchRow.match_date == match_date,
        ))
        return [_match(r) for r in rows]

    def add(self, match: Match) -> Match:
        r = m.MatchRow(league_id=match.league_id, home_team_id=match.home_team_id,
                       away_team_id=match.away_team_id, match_date=match.match_date,
                       kickoff_utc=match.kickoff_utc, ht_home=match.ht_home,
                       ht_away=match.ht_away, ft_home=match.ft_home,
                       ft_away=match.ft_away, status=match.status.value,
                       import_id=match.import_id, dedupe_key=match.dedupe_key)
        self._s.add(r)
        self._s.flush()
        match.id = r.id
        return match

    def update(self, match: Match) -> None:
        r = self._s.get(m.MatchRow, match.id)
        if r is None:
            return
        r.kickoff_utc = match.kickoff_utc
        r.dedupe_key = match.dedupe_key
        r.ht_home, r.ht_away = match.ht_home, match.ht_away
        r.ft_home, r.ft_away = match.ft_home, match.ft_away
        r.status = match.status.value

    def count(self) -> int:
        return int(self._s.scalar(select(func.count(m.MatchRow.id))) or 0)

    def count_by_league(self) -> Dict[int, int]:
        rows = self._s.execute(
            select(m.MatchRow.league_id, func.count(m.MatchRow.id))
            .group_by(m.MatchRow.league_id)
        ).all()
        return {lid: n for lid, n in rows}


class SqlMatchSources:
    def __init__(self, s: Session):
        self._s = s

    def get(self, source: str, external_id: str) -> Optional[MatchSource]:
        r = self._s.scalar(select(m.MatchSourceRow).where(
            m.MatchSourceRow.source == source,
            m.MatchSourceRow.external_id == external_id))
        return MatchSource(r.id, r.match_id, r.source, r.external_id) if r else None

    def add(self, ms: MatchSource) -> MatchSource:
        r = m.MatchSourceRow(match_id=ms.match_id, source=ms.source,
                             external_id=ms.external_id)
        self._s.add(r)
        self._s.flush()
        ms.id = r.id
        return ms


class SqlOdds:
    def __init__(self, s: Session):
        self._s = s

    def add_many(self, quotes: Sequence[OddsQuote]) -> None:
        self._s.add_all([
            m.OddsRow(match_id=q.match_id, bookmaker=q.bookmaker, market=q.market,
                      selection=q.selection, decimal_odds=q.decimal_odds,
                      recorded_at=q.recorded_at, line=q.line, price_point=q.price_point)
            for q in quotes
        ])

    def count(self) -> int:
        return int(self._s.scalar(select(func.count(m.OddsRow.id))) or 0)

    def existing_odds_for_match(
        self, match_id: int
    ) -> Dict[Tuple[str, str, str, Optional[float], Optional[str]], float]:
        rows = self._s.execute(
            select(m.OddsRow.bookmaker, m.OddsRow.market, m.OddsRow.selection,
                   m.OddsRow.line, m.OddsRow.price_point, m.OddsRow.decimal_odds)
            .where(m.OddsRow.match_id == match_id)
        ).all()
        return {(book, mkt, sel, line, pp): odds for book, mkt, sel, line, pp, odds in rows}


class SqlImports:
    def __init__(self, s: Session):
        self._s = s
        self._pending: List[tuple] = []

    def add(self, record: ImportRecord) -> ImportRecord:
        r = m.ImportRow(filename=record.filename, profile_name=record.profile_name,
                        rows_total=record.rows_total, created_at=record.created_at)
        self._s.add(r)
        self._s.flush()
        record.id = r.id
        self._pending.append((record, r))
        return record

    def flush_counters(self) -> None:
        """Sync final counters/report from the domain record before commit."""
        for record, row in self._pending:
            row.rows_imported = record.rows_imported
            row.rows_duplicate = record.rows_duplicate
            row.rows_enriched = record.rows_enriched
            row.rows_rejected = record.rows_rejected
            row.report_json = record.report_json

    def all(self) -> List[ImportRecord]:
        return [ImportRecord(r.id, r.filename, r.profile_name, r.rows_total,
                             r.rows_imported, r.rows_duplicate, r.rows_enriched,
                             r.rows_rejected, r.report_json, r.created_at)
                for r in self._s.scalars(select(m.ImportRow)
                                         .order_by(m.ImportRow.id.desc()))]


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: sessionmaker):
        self._factory = session_factory
        self._session: Optional[Session] = None

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._factory()
        s = self._session
        self.leagues = SqlLeagues(s)
        self.teams = SqlTeams(s)
        self.aliases = SqlAliases(s)
        self.matches = SqlMatches(s)
        self.match_sources = SqlMatchSources(s)
        self.odds = SqlOdds(s)
        self.imports = SqlImports(s)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self._session is not None
        if exc_type:
            self._session.rollback()
        self._session.close()
        self._session = None

    def commit(self) -> None:
        assert self._session is not None
        self.imports.flush_counters()
        self._session.commit()

    def rollback(self) -> None:
        assert self._session is not None
        self._session.rollback()
