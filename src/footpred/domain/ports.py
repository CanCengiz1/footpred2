"""Ports: abstract contracts the application layer codes against.

Everything above infrastructure (ingest pipeline, services, UI) depends only
on these Protocols. Implementations: infra.db.uow (SQLAlchemy/SQLite) and
infra.memory (in-memory, used by the test suite).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Protocol, Sequence

from .entities import (
    ImportRecord,
    League,
    Match,
    MatchSource,
    OddsQuote,
    Team,
    TeamAlias,
)


class LeagueRepository(Protocol):
    def get_by_key(self, canonical_key: str) -> Optional[League]: ...
    def add(self, league: League) -> League: ...
    def all(self) -> List[League]: ...


class TeamRepository(Protocol):
    def get_by_normalized(self, normalized_key: str) -> Optional[Team]: ...
    def add(self, team: Team) -> Team: ...
    def all_normalized(self) -> Dict[str, int]:
        """normalized_key -> team_id, for the fuzzy-match candidate pool."""
        ...


class TeamAliasRepository(Protocol):
    def get_by_normalized(self, normalized_alias: str) -> Optional[TeamAlias]: ...
    def add(self, alias: TeamAlias) -> TeamAlias: ...


class MatchRepository(Protocol):
    def get_by_dedupe_key(self, key: str) -> Optional[Match]: ...
    def find_by_pairing_date(
        self, league_id: int, home_team_id: int, away_team_id: int, match_date: date
    ) -> List[Match]: ...
    def add(self, match: Match) -> Match: ...
    def update(self, match: Match) -> None: ...
    def count(self) -> int: ...
    def count_by_league(self) -> Dict[int, int]: ...


class MatchSourceRepository(Protocol):
    def get(self, source: str, external_id: str) -> Optional[MatchSource]: ...
    def add(self, ms: MatchSource) -> MatchSource: ...


class OddsRepository(Protocol):
    def add_many(self, quotes: Sequence[OddsQuote]) -> None: ...
    def count(self) -> int: ...


class ImportRepository(Protocol):
    def add(self, record: ImportRecord) -> ImportRecord: ...
    def all(self) -> List[ImportRecord]: ...


class UnitOfWork(Protocol):
    """Transaction boundary. One import file == one unit of work."""

    leagues: LeagueRepository
    teams: TeamRepository
    aliases: TeamAliasRepository
    matches: MatchRepository
    match_sources: MatchSourceRepository
    odds: OddsRepository
    imports: ImportRepository

    def __enter__(self) -> "UnitOfWork": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
