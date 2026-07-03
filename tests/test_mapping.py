import json

from footpred.ingest.mapping import (
    FOOTBALL_DATA_CO_UK,
    detect_profile,
    load_profile,
)

FD_COLS = ["Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG",
           "HTHG", "HTAG", "B365H", "B365D", "B365A", "AvgH", "AvgD", "AvgA"]


def test_detects_football_data_layout():
    profile, score = detect_profile(FD_COLS)
    assert profile is FOOTBALL_DATA_CO_UK
    assert score >= 0.7  # all core columns present


def test_partial_odds_columns_lower_score_but_still_detect():
    cols = ["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "B365H"]
    profile, score = detect_profile(cols)
    assert profile is FOOTBALL_DATA_CO_UK
    assert 0.7 <= score < 1.0


def test_unknown_layout_scores_below_auto_apply():
    profile, score = detect_profile(["foo", "bar", "baz"])
    assert score < 0.7


def test_load_custom_profile_from_json(tmp_path):
    spec = {
        "name": "custom", "source_name": "custom",
        "date_col": "d", "home_col": "h", "away_col": "a",
        "fthg_col": "fh", "ftag_col": "fa", "dayfirst": False,
        "fixed_league": ["lg", "League", "Country"],
        "external_id_col": "id",
        "odds_columns": {
            "o1": {"bookmaker": "bet365", "market": "1x2", "selection": "home"}
        },
    }
    p = tmp_path / "custom.json"
    p.write_text(json.dumps(spec), encoding="utf-8")
    profile = load_profile(p)
    assert profile.name == "custom"
    assert profile.fixed_league == ("lg", "League", "Country")
    assert profile.odds_columns["o1"].selection == "home"
    assert profile.detection_score(["d", "h", "a", "fh", "fa", "o1"]) == 1.0
