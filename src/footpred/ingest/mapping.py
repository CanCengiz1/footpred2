"""Flexible column mapping.

A MappingProfile declares how a source file's columns map onto the domain.
Built-in profile covers football-data.co.uk-style files; arbitrary layouts are
supported via JSON profiles (configs/mapping_profiles/*.json) — no code change
needed for a new source.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from footpred.domain.entities import Bookmaker, MARKET_1X2, MARKET_BTTS, MARKET_OU_25


@dataclass(frozen=True)
class OddsColumn:
    bookmaker: str
    market: str
    selection: str


@dataclass
class MappingProfile:
    name: str
    source_name: str                     # tag used in aliases / match_sources
    date_col: str
    home_col: str
    away_col: str
    fthg_col: str
    ftag_col: str
    dayfirst: bool = True
    time_col: Optional[str] = None
    hthg_col: Optional[str] = None
    htag_col: Optional[str] = None
    league_col: Optional[str] = None     # column holding a league code
    league_code_map: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    fixed_league: Optional[Tuple[str, str, str]] = None  # (key, name, country)
    external_id_col: Optional[str] = None
    odds_columns: Dict[str, OddsColumn] = field(default_factory=dict)
    timezone: str = "Europe/Berlin"      # tz naive dates/times are assumed in

    @property
    def core_columns(self) -> List[str]:
        cols = [self.date_col, self.home_col, self.away_col, self.fthg_col, self.ftag_col]
        if self.league_col:
            cols.append(self.league_col)
        return cols

    def missing_core_columns(self, columns: Sequence[str]) -> List[str]:
        """Core columns this file lacks — the UI shows these before import so
        a mis-mapped file fails loudly at preview, not row-by-row later."""
        colset = {c.strip() for c in columns}
        return [c for c in self.core_columns if c not in colset]

    def detection_score(self, columns: Sequence[str]) -> float:
        """0..1 score of how well this profile fits a file's columns.
        Core columns dominate; odds columns refine."""
        colset = {c.strip() for c in columns}
        core = self.core_columns
        core_hits = sum(1 for c in core if c in colset)
        if core_hits < len(core):
            # missing any core column disqualifies heavily
            return 0.4 * core_hits / len(core)
        odds = list(self.odds_columns)
        odds_hits = sum(1 for c in odds if c in colset) / len(odds) if odds else 1.0
        return 0.7 + 0.3 * odds_hits


# --- built-in: football-data.co.uk main leagues layout ---------------------

_FD_LEAGUES: Dict[str, Tuple[str, str]] = {
    "E0": ("Premier League", "England"),
    "E1": ("Championship", "England"),
    "E2": ("League One", "England"),
    "E3": ("League Two", "England"),
    "SC0": ("Scottish Premiership", "Scotland"),
    "D1": ("Bundesliga", "Germany"),
    "D2": ("2. Bundesliga", "Germany"),
    "SP1": ("La Liga", "Spain"),
    "SP2": ("La Liga 2", "Spain"),
    "I1": ("Serie A", "Italy"),
    "I2": ("Serie B", "Italy"),
    "F1": ("Ligue 1", "France"),
    "F2": ("Ligue 2", "France"),
    "N1": ("Eredivisie", "Netherlands"),
    "B1": ("Pro League", "Belgium"),
    "P1": ("Primeira Liga", "Portugal"),
    "T1": ("Super Lig", "Turkey"),
    "G1": ("Super League", "Greece"),
}

_B365 = Bookmaker.BET365.value
_AVG = Bookmaker.MARKET_AVG.value

FOOTBALL_DATA_CO_UK = MappingProfile(
    name="football-data.co.uk",
    source_name="football-data.co.uk",
    date_col="Date",
    time_col="Time",
    home_col="HomeTeam",
    away_col="AwayTeam",
    fthg_col="FTHG",
    ftag_col="FTAG",
    hthg_col="HTHG",
    htag_col="HTAG",
    league_col="Div",
    league_code_map=_FD_LEAGUES,
    dayfirst=True,
    odds_columns={
        "B365H": OddsColumn(_B365, MARKET_1X2, "home"),
        "B365D": OddsColumn(_B365, MARKET_1X2, "draw"),
        "B365A": OddsColumn(_B365, MARKET_1X2, "away"),
        "AvgH": OddsColumn(_AVG, MARKET_1X2, "home"),
        "AvgD": OddsColumn(_AVG, MARKET_1X2, "draw"),
        "AvgA": OddsColumn(_AVG, MARKET_1X2, "away"),
        "B365>2.5": OddsColumn(_B365, MARKET_OU_25, "over"),
        "B365<2.5": OddsColumn(_B365, MARKET_OU_25, "under"),
        "Avg>2.5": OddsColumn(_AVG, MARKET_OU_25, "over"),
        "Avg<2.5": OddsColumn(_AVG, MARKET_OU_25, "under"),
    },
)

BUILTIN_PROFILES: List[MappingProfile] = [FOOTBALL_DATA_CO_UK]


def detect_profile(
    columns: Sequence[str], profiles: Optional[Sequence[MappingProfile]] = None
) -> Tuple[Optional[MappingProfile], float]:
    """Pick the best-scoring profile. Caller decides whether the score is
    good enough to auto-apply (UI requires >= 0.7, i.e. all core columns)."""
    best: Optional[MappingProfile] = None
    best_score = 0.0
    for p in profiles or BUILTIN_PROFILES:
        s = p.detection_score(columns)
        if s > best_score:
            best, best_score = p, s
    return best, best_score


def load_profile(path: str | Path) -> MappingProfile:
    """Load a user-defined profile from JSON. Odds columns are declared as
    {"ColName": {"bookmaker": "...", "market": "...", "selection": "..."}}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    odds = {
        col: OddsColumn(spec["bookmaker"], spec["market"], spec["selection"])
        for col, spec in data.pop("odds_columns", {}).items()
    }
    fixed = data.pop("fixed_league", None)
    return MappingProfile(
        odds_columns=odds,
        fixed_league=tuple(fixed) if fixed else None,
        league_code_map={
            k: tuple(v) for k, v in data.pop("league_code_map", {}).items()
        },
        **data,
    )
