import pandas as pd

from footpred.ingest.mapping import FOOTBALL_DATA_CO_UK as P
from footpred.ingest.validation import ParsedRow, RowError, validate_row


def make_row(**overrides):
    base = {
        "Div": "E0", "Date": "16/08/2025", "Time": "13:30",
        "HomeTeam": "Arsenal", "AwayTeam": "Chelsea",
        "FTHG": 2, "FTAG": 1, "HTHG": 0, "HTAG": 1,
        "B365H": 1.90, "B365D": 3.60, "B365A": 4.20,
    }
    base.update(overrides)
    return pd.Series(base)


def test_valid_row_parses():
    r = validate_row(make_row(), 0, P)
    assert isinstance(r, ParsedRow)
    assert r.match_date.isoformat() == "2025-08-16"
    assert r.kickoff_time is not None and r.kickoff_time.hour == 13
    assert (r.ft_home, r.ft_away, r.ht_home, r.ht_away) == (2, 1, 0, 1)
    assert len(r.odds) == 3
    assert not r.warnings


def test_missing_team_rejected():
    r = validate_row(make_row(HomeTeam=None), 0, P)
    assert isinstance(r, RowError) and "team" in r.reason


def test_identical_teams_rejected():
    r = validate_row(make_row(AwayTeam="Arsenal"), 0, P)
    assert isinstance(r, RowError)


def test_bad_date_rejected():
    r = validate_row(make_row(Date="not-a-date"), 0, P)
    assert isinstance(r, RowError) and "date" in r.reason


def test_missing_ft_rejected():
    r = validate_row(make_row(FTHG=None), 0, P)
    assert isinstance(r, RowError) and "full-time" in r.reason


def test_partial_ht_nulled_with_warning_row_kept():
    r = validate_row(make_row(HTHG=1, HTAG=None), 0, P)
    assert isinstance(r, ParsedRow)
    assert r.ht_home is None and r.ht_away is None
    assert any("half-time" in w for w in r.warnings)


def test_impossible_ht_gt_ft_nulled_with_warning():
    r = validate_row(make_row(HTHG=3, HTAG=0, FTHG=2, FTAG=1), 0, P)
    assert isinstance(r, ParsedRow)
    assert r.ht_home is None
    assert any("impossible" in w for w in r.warnings)


def test_subunity_odds_dropped_with_warning():
    r = validate_row(make_row(B365H=0.5), 0, P)
    assert isinstance(r, ParsedRow)
    assert all(not (o.selection == "home" and o.bookmaker == "bet365") for o in r.odds)
    assert any("< 1.01" in w for w in r.warnings)


def test_overround_sanity_warning():
    # implied sum ~ 3.0 — clearly corrupted / mis-mapped prices
    r = validate_row(make_row(B365H=1.01, B365D=1.01, B365A=1.01), 0, P)
    assert isinstance(r, ParsedRow)
    assert any("implied-prob" in w for w in r.warnings)


def test_date_only_row_has_no_kickoff_time():
    r = validate_row(make_row(Time=None), 0, P)
    assert isinstance(r, ParsedRow)
    assert r.kickoff_time is None
