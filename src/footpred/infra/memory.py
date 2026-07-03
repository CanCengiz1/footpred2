"""In-memory UnitOfWork implementing domain.ports.

Purpose: (a) run the full ingestion test suite with zero DB dependencies,
(b) serve as the behavioural reference for the SQLAlchemy implementation.
"""
from __future__ import annotations

import itertools
from datetime import date
from typing import Dict, List, Optional, Sequence

from footpred.domain.entities import (
    ImportRecord,
    League,
    Match,
    MatchSource,
    OddsQuote,
    Team,
    TeamAlias,
)


class _Seq:
    def __init__(self) -> None:
        self._c = itertools.count(1)

    def next(self) -> int:
        return next(self._c)


class InMemoryLeagues:
    def __init__(self) -> None:
        self._by_key: Dict[str, League] = {}
        self._seq = _Seq()

    def get_by_key(self, canonical_key: str) -> Optional[League]:
        return self._by_key.get(canonical_key)

    def add(self, league: League) -> League:
        league.id = self._seq.next()
        self._by_key[league.canonical_key] = league
        return league

    def all(self) -> List[League]:
        return list(self._by_key.values())


class InMemoryTeams:
    def __init__(self) -> None:
        self._by_norm: Dict[str, Team] = {}
        self._seq = _Seq()

    def get_by_normalized(self, normalized_key: str) -> Optional[Team]:
        return self._by_norm.get(normalized_key)

    def add(self, team: Team) -> Team:
        team.id = self._seq.next()
        self._by_norm[team.normalized_key] = team
        return team

    def all_normalized(self) -> Dict[str, int]:
        return {k: t.id for k, t in self._by_norm.items()}  # type: ignore[misc]


class InMemoryAliases:
    def __init__(self) -> None:
        self._by_norm: Dict[str, TeamAlias] = {}
        self._seq = _Seq()

    def get_by_normalized(self, normalized_alias: str) -> Optional[TeamAlias]:
        return self._by_norm.get(normalized_alias)

    def add(self, alias: TeamAlias) -> TeamAlias:
        alias.id = self._seq.next()
        self._by_norm[alias.normalized_alias] = alias
        return alias


class InMemoryMatches:
    def __init__(self) -> None:
        self._items: List[Match] = []
        self._seq = _Seq()

    def get_by_dedupe_key(self, key: str) -> Optional[Match]:
        return next((m for m in self._items if m.dedupe_key == key), None)

    def find_by_pairing_date(
        self, league_id: int, home_team_id: int, away_team_id: int, match_date: date
    ) -> List[Match]:
        return [
            m
            for m in self._items
            if m.league_id == league_id
            and m.home_team_id == home_team_id
            and m.away_team_id == away_team_id
            and m.match_date == match_date
        ]

    def add(self, match: Match) -> Match:
        match.id = self._seq.next()
        self._items.append(match)
        return match

    def update(self, match: Match) -> None:
        pass  # objects are mutated in place

    def count(self) -> int:
        return len(self._items)

    def count_by_league(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for m in self._items:
            out[m.league_id] = out.get(m.league_id, 0) + 1
        return out


class InMemoryMatchSources:
    def __init__(self) -> None:
        self._by_key: Dict[tuple, MatchSource] = {}
        self._seq = _Seq()

    def get(self, source: str, external_id: str) -> Optional[MatchSource]:
        return self._by_key.get((source, external_id))

    def add(self, ms: MatchSource) -> MatchSource:
        ms.id = self._seq.next()
        self._by_key[(ms.source, ms.external_id)] = ms
        return ms


class InMemoryOdds:
    def __init__(self) -> None:
        self.items: List[OddsQuote] = []
        self._seq = _Seq()

    def add_many(self, quotes: Sequence[OddsQuote]) -> None:
        for q in quotes:
            q.id = self._seq.next()
            self.items.append(q)

    def count(self) -> int:
        return len(self.items)


class InMemoryImports:
    def __init__(self) -> None:
        self.items: List[ImportRecord] = []
        self._seq = _Seq()

    def add(self, record: ImportRecord) -> ImportRecord:
        record.id = self._seq.next()
        self.items.append(record)
        return record

    def all(self) -> List[ImportRecord]:
        return list(self.items)


class InMemoryUnitOfWork:
    def __init__(self) -> None:
        self.leagues = InMemoryLeagues()
        self.teams = InMemoryTeams()
        self.aliases = InMemoryAliases()
        self.matches = InMemoryMatches()
        self.match_sources = InMemoryMatchSources()
        self.odds = InMemoryOdds()
        self.imports = InMemoryImports()
        self.committed = 0

    def __enter__(self) -> "InMemoryUnitOfWork":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            self.rollback()

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:  # pragma: no cover - nothing to undo in memory
        pass
