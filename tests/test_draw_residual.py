import math
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd

from footpred.ml.models.dixon_coles import DixonColesModel
from footpred.ml.models.draw_residual import RESIDUAL_COLS, compute_draw_residual_features


def _toy_matches(n_teams=4, n_rounds=3, seed=0):
    """Deterministic small round-robin -- enough repetition per team for
    both DC to fit and leave-one-out denominators to be > 0."""
    rng = np.random.default_rng(seed)
    rows = []
    d = date(2020, 8, 1)
    match_id = 0
    for _ in range(n_rounds):
        for i in range(n_teams):
            for j in range(n_teams):
                if i == j:
                    continue
                rows.append({
                    "match_id": match_id, "league_key": "L1",
                    "home_team_id": i, "away_team_id": j,
                    "ft_home": int(rng.poisson(1.3)), "ft_away": int(rng.poisson(1.1)),
                    "match_date": d,
                })
                match_id += 1
                d += timedelta(days=1)
    return pd.DataFrame(rows).set_index("match_id")


# --------------------------- shape / bounds ---------------------------- #

def test_output_shape_and_bounds():
    frame = _toy_matches()
    train_mask = pd.Series(True, index=frame.index)
    train_mask.iloc[-8:] = False

    out = compute_draw_residual_features(frame, train_mask)
    assert list(out.columns) == RESIDUAL_COLS
    assert out.index.equals(frame.index)
    valid = out.dropna()
    assert not valid.empty
    assert (valid >= -1.0).all().all()
    assert (valid <= 1.0).all().all()


# --------------------------- leave-one-out arithmetic ------------------- #

def test_leave_one_out_matches_manual_computation():
    frame = _toy_matches()
    train_mask = pd.Series(True, index=frame.index)
    train_mask.iloc[-6:] = False

    out = compute_draw_residual_features(frame, train_mask)

    # Independently reproduce the same fit/residuals and check the
    # leave-one-out arithmetic by hand, rather than trusting the function's
    # own internals.
    train_rows = frame[train_mask]
    model = DixonColesModel(xi=0.001)
    model.fit(train_rows[["home_team_id", "away_team_id", "ft_home", "ft_away", "match_date"]])
    predicted = train_rows.apply(
        lambda r: model.predict_1x2(r["home_team_id"], r["away_team_id"])[1], axis=1)
    actual = (train_rows["ft_home"] == train_rows["ft_away"]).astype(float)
    residual = actual - predicted

    appearances = pd.concat([
        pd.DataFrame({"team_id": train_rows["home_team_id"], "residual": residual}),
        pd.DataFrame({"team_id": train_rows["away_team_id"], "residual": residual}),
    ])
    team_total = appearances.groupby("team_id")["residual"].sum()
    team_n = appearances.groupby("team_id")["residual"].count()

    m = train_rows.index[0]
    home_team = train_rows.loc[m, "home_team_id"]
    expected_home = (team_total[home_team] - residual.loc[m]) / (team_n[home_team] - 1)
    assert math.isclose(out.loc[m, "home_draw_residual"], expected_home, abs_tol=1e-9)


# --------------------------- no self-outcome leakage --------------------- #

def test_no_self_outcome_leakage_on_training_rows():
    """With predict_1x2 mocked to a fixed constant (removing DC's own
    fit-sensitivity to the perturbation as a confound), a training match's
    leave-one-out feature must be provably independent of its own outcome:
    algebraically, (team_total - residual_m) cancels residual_m exactly.
    Perturbing match m's own outcome must leave m's own feature unchanged,
    while changing a DIFFERENT match of the same team (proving the
    perturbation had a real, detectable effect -- just not on itself)."""
    frame = _toy_matches(n_rounds=4)
    train_mask = pd.Series(True, index=frame.index)
    train_mask.iloc[-6:] = False

    with patch.object(DixonColesModel, "predict_1x2", return_value=(0.4, 0.3, 0.3)):
        out_before = compute_draw_residual_features(frame, train_mask)

        m = frame[train_mask].index[0]
        home_team = frame.loc[m, "home_team_id"]
        other_candidates = frame[train_mask & (frame["home_team_id"] == home_team)
                                  & (frame.index != m)]
        other_m = other_candidates.index[0]

        frame2 = frame.copy()
        if frame2.loc[m, "ft_home"] == frame2.loc[m, "ft_away"]:
            frame2.loc[m, "ft_away"] += 1  # was a draw -> make it not
        else:
            frame2.loc[m, "ft_away"] = frame2.loc[m, "ft_home"]  # make it a draw

        out_after = compute_draw_residual_features(frame2, train_mask)

    assert math.isclose(out_before.loc[m, "home_draw_residual"],
                         out_after.loc[m, "home_draw_residual"], abs_tol=1e-9)
    assert not math.isclose(out_before.loc[other_m, "home_draw_residual"],
                             out_after.loc[other_m, "home_draw_residual"], abs_tol=1e-9)


# --------------------------- test rows: train-window only --------------- #

def test_test_rows_use_training_window_residuals_only():
    frame = _toy_matches(n_rounds=4)
    train_mask = pd.Series(True, index=frame.index)
    train_mask.iloc[-6:] = False

    out_before = compute_draw_residual_features(frame, train_mask)

    frame2 = frame.copy()
    test_idx = frame[~train_mask].index[0]
    frame2.loc[test_idx, "ft_home"] = frame2.loc[test_idx, "ft_home"] + 3
    out_after = compute_draw_residual_features(frame2, train_mask)

    pd.testing.assert_frame_equal(out_before, out_after)


# --------------------------- edge case: thin history --------------------- #

def test_insufficient_training_history_gives_nan_not_crash():
    frame = _toy_matches(n_rounds=2)
    train_mask = pd.Series(True, index=frame.index)

    lone_team = frame["home_team_id"].iloc[0]
    team_train_rows = frame[train_mask & ((frame.home_team_id == lone_team)
                                          | (frame.away_team_id == lone_team))]
    train_mask.loc[team_train_rows.index[1:]] = False  # leave exactly one

    out = compute_draw_residual_features(frame, train_mask)
    m = team_train_rows.index[0]
    if frame.loc[m, "home_team_id"] == lone_team:
        assert np.isnan(out.loc[m, "home_draw_residual"])
    else:
        assert np.isnan(out.loc[m, "away_draw_residual"])
