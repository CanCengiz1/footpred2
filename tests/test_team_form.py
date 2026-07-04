import math
from datetime import date, timedelta

from footpred.domain.entities import League, Match, MatchStatus, Team
from footpred.infra.memory import InMemoryUnitOfWork
from footpred.infra.read_models import InMemoryMatchOddsReader
from footpred.ml.datasets import DatasetBuilder
from footpred.ml.features.base import FeatureContext, get_feature_group
from footpred.ml.splits import GroupFractionSplit


def _make_uow_with_matches(fixtures):
    """fixtures: list of (home_name, away_name, match_date, ft_home, ft_away),
    inserted in order so match_id and team_id assignment is deterministic."""
    uow = InMemoryUnitOfWork()
    league = uow.leagues.add(League(id=None, canonical_key="test_league", name="Test League"))
    team_ids = {}

    def team_id(name):
        if name not in team_ids:
            t = uow.teams.add(Team(id=None, canonical_name=name, normalized_key=name.lower()))
            team_ids[name] = t.id
        return team_ids[name]

    for home, away, d, fh, fa in fixtures:
        uow.matches.add(Match(
            id=None, league_id=league.id, home_team_id=team_id(home),
            away_team_id=team_id(away), match_date=d, kickoff_utc=None,
            ht_home=None, ht_away=None, ft_home=fh, ft_away=fa,
            status=MatchStatus.COMPLETED, import_id=None,
        ))
    return uow, team_ids


def _build_form(uow):
    frame = InMemoryMatchOddsReader(uow).load_completed()
    feats = get_feature_group("team_form").build(FeatureContext(matches=frame))
    return frame, feats


def test_first_ever_match_has_no_history():
    uow, _ = _make_uow_with_matches([
        ("Arsenal", "Chelsea", date(2025, 8, 16), 2, 1),
    ])
    _, feats = _build_form(uow)
    row = feats.iloc[0]
    for w in (5, 10):
        assert math.isnan(row[f"home_form_pts_last{w}"])
        assert math.isnan(row[f"away_form_pts_last{w}"])
        assert row[f"home_form_n_last{w}"] == 0
        assert row[f"away_form_n_last{w}"] == 0


def test_rolling_form_matches_hand_computation():
    fixtures = [
        ("A", "B", date(2025, 1, 1), 2, 1),   # A: pts3 gf2 ga1 (home) | B: pts0 gf1 ga2 (away)
        ("C", "A", date(2025, 1, 8), 0, 0),   # C: pts1 (home)         | A: pts1 gf0 ga0 (away)
        ("A", "D", date(2025, 1, 15), 1, 3),  # A: pts0 gf1 ga3 (home) | D: pts3 gf3 ga1 (away)
        ("B", "A", date(2025, 1, 22), 2, 2),  # B: pts1 (home)         | A: pts1 gf2 ga2 (away)
    ]
    uow, _ = _make_uow_with_matches(fixtures)
    frame, feats = _build_form(uow)

    match4_id = frame.loc[frame["match_date"] == date(2025, 1, 22), "match_id"].iloc[0]
    row = feats.loc[match4_id]

    # away side of match 4 is A; A's prior history: pts [3,1,0], gf [2,0,1], ga [1,0,3]
    assert math.isclose(row["away_form_pts_last5"], (3 + 1 + 0) / 3, abs_tol=1e-9)
    assert math.isclose(row["away_form_gf_last5"], (2 + 0 + 1) / 3, abs_tol=1e-9)
    assert math.isclose(row["away_form_ga_last5"], (1 + 0 + 3) / 3, abs_tol=1e-9)
    assert math.isclose(row["away_form_gd_last5"],
                         row["away_form_gf_last5"] - row["away_form_ga_last5"], abs_tol=1e-12)
    assert row["away_form_n_last5"] == 3
    # window=10 identical here: A only has 3 prior matches, well under either window
    assert math.isclose(row["away_form_pts_last10"], row["away_form_pts_last5"], abs_tol=1e-9)
    assert row["away_form_n_last10"] == 3

    # home side of match 4 is B; B's only prior match is match 1 (as away): pts0 gf1 ga2
    assert math.isclose(row["home_form_pts_last5"], 0.0, abs_tol=1e-9)
    assert math.isclose(row["home_form_gf_last5"], 1.0, abs_tol=1e-9)
    assert math.isclose(row["home_form_ga_last5"], 2.0, abs_tol=1e-9)
    assert row["home_form_n_last5"] == 1


def test_window_size_truncates_to_most_recent_n():
    opponents = ["B", "C", "D", "E", "F", "G"]
    ft_scores = [(1, 0)] * 5 + [(0, 1)]  # A: win,win,win,win,win,loss -> pts 3,3,3,3,3,0
    fixtures = []
    d = date(2025, 1, 1)
    for opp, (fh, fa) in zip(opponents, ft_scores):
        fixtures.append(("A", opp, d, fh, fa))
        d += timedelta(days=7)
    fixtures.append(("A", "H", d, 1, 1))  # 7th match: the one whose form we inspect

    uow, _ = _make_uow_with_matches(fixtures)
    frame, feats = _build_form(uow)
    match7_id = frame.sort_values("match_date")["match_id"].iloc[-1]
    row = feats.loc[match7_id]

    # last5 = matches 2..6 (pts 3,3,3,3,0); last10 = all 6 matches (pts 3,3,3,3,3,0)
    assert math.isclose(row["home_form_pts_last5"], (3 + 3 + 3 + 3 + 0) / 5, abs_tol=1e-9)
    assert row["home_form_n_last5"] == 5
    assert math.isclose(row["home_form_pts_last10"], (3 * 5 + 0) / 6, abs_tol=1e-9)
    assert row["home_form_n_last10"] == 6


def test_earlier_matches_immune_to_later_score_changes():
    base_fixtures = [
        ("A", "B", date(2025, 1, 1), 2, 1),
        ("C", "A", date(2025, 1, 8), 0, 0),
        ("A", "D", date(2025, 1, 15), 1, 3),
        ("B", "A", date(2025, 1, 22), 2, 2),
    ]
    changed_fixtures = list(base_fixtures)
    changed_fixtures[2] = ("A", "D", date(2025, 1, 15), 5, 0)  # change match 3's score only

    uow1, _ = _make_uow_with_matches(base_fixtures)
    frame1, feats1 = _build_form(uow1)
    uow2, _ = _make_uow_with_matches(changed_fixtures)
    frame2, feats2 = _build_form(uow2)

    id1 = frame1.loc[frame1["match_date"] == date(2025, 1, 1), "match_id"].iloc[0]
    id2 = frame1.loc[frame1["match_date"] == date(2025, 1, 8), "match_id"].iloc[0]
    id4 = frame1.loc[frame1["match_date"] == date(2025, 1, 22), "match_id"].iloc[0]

    # matches strictly before the changed match are untouched
    assert feats1.loc[id1].equals(feats2.loc[id1])
    assert feats1.loc[id2].equals(feats2.loc[id2])
    # match 4, which follows the changed match, must reflect the new numbers
    assert not feats1.loc[id4].equals(feats2.loc[id4])
    assert math.isclose(feats2.loc[id4]["away_form_gf_last5"], (2 + 0 + 5) / 3, abs_tol=1e-9)
    assert math.isclose(feats2.loc[id4]["away_form_ga_last5"], (1 + 0 + 0) / 3, abs_tol=1e-9)


def test_team_form_flows_into_dataset_without_collision():
    fixtures = [
        ("A", "B", date(2025, 1, 1), 2, 1),
        ("C", "A", date(2025, 1, 8), 0, 0),
        ("A", "D", date(2025, 1, 15), 1, 3),
        ("B", "A", date(2025, 1, 22), 2, 2),
        ("A", "C", date(2025, 1, 29), 1, 1),
    ]
    uow, _ = _make_uow_with_matches(fixtures)
    reader = InMemoryMatchOddsReader(uow)
    builder = DatasetBuilder(reader, feature_groups=["odds_core", "team_form"],
                              split=GroupFractionSplit(0.6))
    frame, manifest = builder.build()

    assert "home_form_pts_last5" in frame.columns
    assert "away_form_n_last10" in frame.columns
    names = {g["name"]: g["version"] for g in manifest["feature_groups"]}
    assert names["team_form"] == "1.0"
