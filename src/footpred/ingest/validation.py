"""Row validation and parsing.

Converts a raw file row (via a MappingProfile) into a ParsedRow, or a
RowError with a human-readable reason. Policies implemented here:

- FT scores mandatory for historical results (reject otherwise).
- HT scores optional; if only one side present or HT > FT (impossible),
  HT is nulled with a warning — the row still serves standard markets.
- Odds < 1.01 or unparseable: that quote is dropped with a warning; the
  match itself is kept.
- 1X2 overround sanity: implied-probability sum outside [1.00, 1.25]
  produces a warning (possible mis-mapped columns or corrupted prices).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import List, Optional, Tuple

import pandas as pd

from footpred.domain.entities import MARKET_1X2
from footpred.ingest.mapping import MappingProfile, OddsColumn


@dataclass
class ParsedOdds:
    bookmaker: str
    market: str
    selection: str
    decimal_odds: float


@dataclass
class ParsedRow:
    row_index: int
    league_raw: Optional[str]
    home_raw: str
    away_raw: str
    match_date: date
    kickoff_time: Optional[time]        # naive, in the profile's timezone
    ft_home: int
    ft_away: int
    ht_home: Optional[int]
    ht_away: Optional[int]
    external_id: Optional[str]
    odds: List[ParsedOdds] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class RowError:
    row_index: int
    reason: str


def _is_missing(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v)


def _as_int(v) -> Optional[int]:
    if _is_missing(v):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != int(f) or f < 0:
        return None
    return int(f)


def _as_odds(v) -> Optional[float]:
    if _is_missing(v):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _parse_date(v, dayfirst: bool) -> Optional[date]:
    if _is_missing(v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        ts = pd.to_datetime(str(v).strip(), dayfirst=dayfirst)
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def _parse_time(v) -> Optional[time]:
    if _is_missing(v):
        return None
    if isinstance(v, time):
        return v
    if isinstance(v, datetime):
        return v.time()
    try:
        ts = pd.to_datetime(str(v).strip())
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts.time()


def validate_row(row: pd.Series, row_index: int, profile: MappingProfile):
    """Return ParsedRow or RowError."""
    home = None if _is_missing(row.get(profile.home_col)) else str(row.get(profile.home_col)).strip()
    away = None if _is_missing(row.get(profile.away_col)) else str(row.get(profile.away_col)).strip()
    if not home or not away:
        return RowError(row_index, "missing home or away team name")
    if home.lower() == away.lower():
        return RowError(row_index, "home and away team are identical")

    match_date = _parse_date(row.get(profile.date_col), profile.dayfirst)
    if match_date is None:
        return RowError(row_index, f"unparseable date: {row.get(profile.date_col)!r}")

    ft_home = _as_int(row.get(profile.fthg_col))
    ft_away = _as_int(row.get(profile.ftag_col))
    if ft_home is None or ft_away is None:
        return RowError(row_index, "missing or invalid full-time score")

    warnings: List[str] = []

    ht_home = _as_int(row.get(profile.hthg_col)) if profile.hthg_col else None
    ht_away = _as_int(row.get(profile.htag_col)) if profile.htag_col else None
    if (ht_home is None) != (ht_away is None):
        warnings.append("half-time score incomplete; HT dropped, row kept for FT markets")
        ht_home = ht_away = None
    elif ht_home is not None and (ht_home > ft_home or ht_away > ft_away):
        warnings.append(
            f"impossible HT>FT ({ht_home}-{ht_away} vs {ft_home}-{ft_away}); HT dropped"
        )
        ht_home = ht_away = None

    kickoff_time = _parse_time(row.get(profile.time_col)) if profile.time_col else None

    league_raw = None
    if profile.league_col:
        v = row.get(profile.league_col)
        league_raw = None if _is_missing(v) else str(v).strip()

    external_id = None
    if profile.external_id_col:
        v = row.get(profile.external_id_col)
        external_id = None if _is_missing(v) else str(v).strip()

    odds, odds_warnings = _parse_odds(row, profile)
    warnings.extend(odds_warnings)

    return ParsedRow(
        row_index=row_index,
        league_raw=league_raw,
        home_raw=home,
        away_raw=away,
        match_date=match_date,
        kickoff_time=kickoff_time,
        ft_home=ft_home,
        ft_away=ft_away,
        ht_home=ht_home,
        ht_away=ht_away,
        external_id=external_id,
        odds=odds,
        warnings=warnings,
    )


def _parse_odds(
    row: pd.Series, profile: MappingProfile
) -> Tuple[List[ParsedOdds], List[str]]:
    odds: List[ParsedOdds] = []
    warnings: List[str] = []
    for col, spec in profile.odds_columns.items():
        if col not in row.index:
            continue
        price = _as_odds(row.get(col))
        if price is None:
            continue  # silently absent — not every market is quoted for every match
        if price < 1.01:
            warnings.append(f"odds {col}={price} < 1.01 dropped")
            continue
        odds.append(ParsedOdds(spec.bookmaker, spec.market, spec.selection, price))

    # 1X2 overround sanity per bookmaker
    for book in {o.bookmaker for o in odds}:
        trio = [o for o in odds if o.bookmaker == book and o.market == MARKET_1X2]
        if len(trio) == 3:
            s = sum(1.0 / o.decimal_odds for o in trio)
            if not (1.00 <= s <= 1.25):
                warnings.append(
                    f"1X2 implied-prob sum for {book} is {s:.3f} (outside [1.00, 1.25])"
                )
    return odds, warnings
