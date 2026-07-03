"""Entity resolution for teams and leagues.

Cascade per raw team name:
  1. exact normalized match against teams or the alias table  -> resolve
  2. fuzzy match (difflib ratio >= threshold, default 0.92)   -> resolve,
     and PERSIST the alias so the decision is remembered and auditable
  3. no match -> create the team, flag "created" in the report

The threshold is conservative on purpose: a false merge silently corrupts
every downstream feature, a false split is visible and fixable via the alias
table. Every non-exact decision is surfaced in the import report.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Optional

from footpred.domain.entities import League, Team, TeamAlias
from footpred.domain.ports import UnitOfWork
from footpred.ingest.mapping import MappingProfile

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """lowercase, fold accents, strip punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", raw)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


@dataclass
class Resolution:
    team_id: int
    kind: str            # "exact" | "alias" | "fuzzy" | "created"
    raw: str
    matched_key: Optional[str] = None
    confidence: float = 1.0


class TeamResolver:
    def __init__(self, uow: UnitOfWork, source: str, fuzzy_threshold: float = 0.92):
        self._uow = uow
        self._source = source
        self._threshold = fuzzy_threshold
        # candidate pool: normalized_key -> team_id (teams + session-created)
        self._pool: Dict[str, int] = dict(uow.teams.all_normalized())
        self._cache: Dict[str, Resolution] = {}

    def resolve(self, raw: str) -> Resolution:
        norm = normalize_name(raw)
        if norm in self._cache:
            return self._cache[norm]
        res = self._resolve_uncached(raw, norm)
        self._cache[norm] = res
        return res

    def _resolve_uncached(self, raw: str, norm: str) -> Resolution:
        # 1a. exact against canonical team keys
        team_id = self._pool.get(norm)
        if team_id is not None:
            return Resolution(team_id, "exact", raw, norm)
        # 1b. exact against remembered aliases
        alias = self._uow.aliases.get_by_normalized(norm)
        if alias is not None:
            return Resolution(alias.team_id, "alias", raw, alias.normalized_alias,
                              alias.confidence)
        # 2. fuzzy against candidate pool
        candidates = difflib.get_close_matches(norm, self._pool.keys(), n=1,
                                               cutoff=self._threshold)
        if candidates:
            key = candidates[0]
            ratio = difflib.SequenceMatcher(None, norm, key).ratio()
            team_id = self._pool[key]
            self._uow.aliases.add(TeamAlias(
                id=None, team_id=team_id, alias=raw, normalized_alias=norm,
                source=self._source, confidence=round(ratio, 4),
            ))
            return Resolution(team_id, "fuzzy", raw, key, round(ratio, 4))
        # 3. create
        team = self._uow.teams.add(Team(id=None, canonical_name=raw, normalized_key=norm))
        self._uow.aliases.add(TeamAlias(
            id=None, team_id=team.id, alias=raw, normalized_alias=norm,  # type: ignore[arg-type]
            source=self._source, confidence=1.0,
        ))
        self._pool[norm] = team.id  # type: ignore[assignment]
        return Resolution(team.id, "created", raw, norm)  # type: ignore[arg-type]


class LeagueResolver:
    """Resolves a league code/name (or the profile's fixed league) to a
    League row, creating it on first sight."""

    def __init__(self, uow: UnitOfWork, profile: MappingProfile):
        self._uow = uow
        self._profile = profile
        self._cache: Dict[str, League] = {}

    def resolve(self, league_raw: Optional[str]) -> Optional[League]:
        if league_raw is None and self._profile.fixed_league is None:
            return None
        if league_raw is not None:
            key = league_raw.strip()
            mapped = self._profile.league_code_map.get(key)
            name, country = mapped if mapped else (key, None)
        else:
            key, name, country = self._profile.fixed_league  # type: ignore[misc]
        if key in self._cache:
            return self._cache[key]
        league = self._uow.leagues.get_by_key(key)
        if league is None:
            league = self._uow.leagues.add(
                League(id=None, canonical_key=key, name=name, country=country)
            )
        self._cache[key] = league
        return league
