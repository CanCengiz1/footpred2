"""Domain entities. Pure dataclasses — no ORM, no pandas, no framework imports.

Design notes (Sprint 1):
- ``Match.match_date`` is identity data (always known, as given by the source).
- ``Match.kickoff_utc`` is precision data (nullable, enriched when a better
  source provides it). Never fabricate midnight timestamps.
- ``Match.dedupe_key`` is a deterministic natural key used for reconciliation
  when no external source ID is available.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class MatchStatus(str, Enum):
    COMPLETED = "completed"   # has full-time result
    SCHEDULED = "scheduled"   # future match (used from Sprint 4 on)


class Bookmaker(str, Enum):
    BET365 = "bet365"
    MARKET_AVG = "market_avg"
    PINNACLE = "pinnacle"


# Markets are open strings by design (new markets must not require schema or
# enum changes). These constants cover Sprint 1 sources.
MARKET_1X2 = "1x2"
MARKET_OU_25 = "ou_2.5"
MARKET_BTTS = "btts"
MARKET_AH = "ah"


@dataclass
class League:
    id: Optional[int]
    canonical_key: str          # normalized stable key, e.g. "eng_premier_league" or "E0"
    name: str
    country: Optional[str] = None


@dataclass
class Team:
    id: Optional[int]
    canonical_name: str
    normalized_key: str


@dataclass
class TeamAlias:
    id: Optional[int]
    team_id: int
    alias: str                  # raw form as seen in a source
    normalized_alias: str
    source: str                 # which import/profile produced it
    confidence: float           # 1.0 exact/created, <1.0 fuzzy


@dataclass
class Match:
    id: Optional[int]
    league_id: int
    home_team_id: int
    away_team_id: int
    match_date: date            # identity: local date as given by the source
    kickoff_utc: Optional[datetime]  # precision: UTC instant when known
    ht_home: Optional[int]
    ht_away: Optional[int]
    ft_home: Optional[int]
    ft_away: Optional[int]
    status: MatchStatus
    import_id: Optional[int]
    dedupe_key: str = ""

    def has_halftime(self) -> bool:
        return self.ht_home is not None and self.ht_away is not None


def make_dedupe_key(
    league_id: int,
    home_team_id: int,
    away_team_id: int,
    match_date: date,
    kickoff_utc: Optional[datetime],
) -> str:
    """Deterministic natural key. Time participates only when known, so a
    date-only row and a timed row for the same fixture do NOT collide here —
    reconciliation of that case is the pipeline's enrichment rule."""
    time_part = kickoff_utc.strftime("%H:%M") if kickoff_utc is not None else "NA"
    return f"{league_id}|{home_team_id}|{away_team_id}|{match_date.isoformat()}|{time_part}"


@dataclass
class MatchSource:
    """External identity of a match in some source system (CSV provider,
    future odds API...). One match may accumulate many of these."""
    id: Optional[int]
    match_id: int
    source: str
    external_id: str


@dataclass
class OddsQuote:
    id: Optional[int]
    match_id: int
    bookmaker: str              # Bookmaker value or future book name
    market: str                 # e.g. "1x2", "ou_2.5", "btts", "ht_ft"
    selection: str              # e.g. "home"/"draw"/"away", "over"/"under"
    decimal_odds: float
    recorded_at: Optional[datetime] = None   # None == unknown odds timing
    line: Optional[float] = None             # numeric line, e.g. an Asian
                                              # Handicap value; None for
                                              # markets with no line (1x2)
    price_point: Optional[str] = None        # "opening" / "closing" / None
                                              # (unspecified — the original
                                              # single-snapshot convention)

    def identity_key(self) -> tuple:
        """(bookmaker, market, selection, line, price_point) — the tuple that
        determines whether two quotes represent the "same" price point, used
        by the ingest pipeline's odds-backfill reconciliation. Deliberately
        excludes match_id/id/decimal_odds: two quotes with this same tuple
        for the same match are the same observation, not two different ones,
        even if their prices differ (a differing price is a conflict to
        surface, not a second quote to store)."""
        return (self.bookmaker, self.market, self.selection, self.line, self.price_point)


@dataclass
class ImportRecord:
    id: Optional[int]
    filename: str
    profile_name: str
    rows_total: int
    rows_imported: int
    rows_duplicate: int
    rows_enriched: int
    rows_rejected: int
    report_json: str
    created_at: datetime = field(default_factory=datetime.utcnow)
