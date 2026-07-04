"""Draw-tendency residual: a team's historical tendency to draw more or less
than the audited Dixon-Coles model predicts, as a Stage 2 ablation candidate
feature -- the closure test for the team-scoreline-derived hypothesis
category (see docs/RESEARCH_RETROSPECTIVE.md).

Deliberately NOT a registered FeatureGroup: it hasn't cleared ablation yet,
same convention as tabular.py's odds_consensus/odds_divergence/extra_columns
(build one-off analysis features without prematurely promoting them).

Scope, agreed before implementation:
  - draw residual only, pooled across venue (no home/away split -- that
    hypothesis already failed on its own).
  - one Dixon-Coles fit per (league, train/test split), not a sequential
    per-historical-match refit.
  - training rows get a leave-one-out residual, excluding that match's own
    outcome from its own team's average -- the same self-exclusion
    discipline team_form's .shift(1) applies, adapted to a fold-level
    (not per-match rolling) construction. Without this, a training row's
    feature would partly reflect its own outcome.
  - test rows use the plain training-window average (no exclusion needed --
    they were never part of it, so there is nothing to leak).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from footpred.ml.models.dixon_coles import DixonColesModel

RESIDUAL_COLS = ["home_draw_residual", "away_draw_residual"]


def compute_draw_residual_features(
    frame: pd.DataFrame, train_mask: pd.Series, xi: float = 0.001,
) -> pd.DataFrame:
    """frame: needs league_key, home_team_id, away_team_id, ft_home, ft_away,
    match_date. train_mask: boolean Series aligned to frame.index (True for
    training rows for this split).

    Fits one DixonColesModel per league on train_mask rows only. Returns a
    frame (same index as `frame`) with home_draw_residual/away_draw_residual,
    NaN wherever a team has no (or, for the leave-one-out case, no other)
    training-window appearance to draw a residual from -- left for
    downstream imputation, same convention as every other feature here.
    """
    out = pd.DataFrame(index=frame.index, columns=RESIDUAL_COLS, dtype=float)

    for league, league_frame in frame.groupby("league_key"):
        league_train_mask = train_mask.loc[league_frame.index]
        train_rows = league_frame[league_train_mask]
        test_rows = league_frame[~league_train_mask]
        if train_rows.empty:
            continue

        model = DixonColesModel(xi=xi)
        model.fit(train_rows[["home_team_id", "away_team_id", "ft_home", "ft_away", "match_date"]])

        predicted_draw = train_rows.apply(
            lambda r: model.predict_1x2(r["home_team_id"], r["away_team_id"])[1], axis=1)
        actual_draw = (train_rows["ft_home"] == train_rows["ft_away"]).astype(float)
        residual = actual_draw - predicted_draw  # in [-1, 1]

        appearances = pd.concat([
            pd.DataFrame({"team_id": train_rows["home_team_id"], "residual": residual}),
            pd.DataFrame({"team_id": train_rows["away_team_id"], "residual": residual}),
        ])
        team_total = appearances.groupby("team_id")["residual"].sum()
        team_n = appearances.groupby("team_id")["residual"].count()

        def _leave_one_out(team_ids: pd.Series, own_residual: pd.Series) -> np.ndarray:
            total = team_total.reindex(team_ids).to_numpy()
            n = team_n.reindex(team_ids).to_numpy()
            denom = n - 1.0
            with np.errstate(invalid="ignore", divide="ignore"):
                result = (total - own_residual.to_numpy()) / denom
            result[denom <= 0] = np.nan
            return result

        def _plain_mean(team_ids: pd.Series) -> np.ndarray:
            total = team_total.reindex(team_ids).to_numpy()
            n = team_n.reindex(team_ids).to_numpy()
            with np.errstate(invalid="ignore", divide="ignore"):
                result = total / n
            result[n <= 0] = np.nan
            return result

        out.loc[train_rows.index, "home_draw_residual"] = _leave_one_out(
            train_rows["home_team_id"], residual)
        out.loc[train_rows.index, "away_draw_residual"] = _leave_one_out(
            train_rows["away_team_id"], residual)

        if not test_rows.empty:
            out.loc[test_rows.index, "home_draw_residual"] = _plain_mean(test_rows["home_team_id"])
            out.loc[test_rows.index, "away_draw_residual"] = _plain_mean(test_rows["away_team_id"])

    return out
