"""Team-form features (feature group "team_form", v1.0).

As-of, leakage-free rolling form per team over its last N matches — any
venue, any league (a team's real match history isn't fragmented by
division; a team's E1 history carries into its E0 matches after
promotion, and vice versa). Each match is scored from the team's own
history strictly BEFORE that match's date; the match itself never
contributes to its own features.

Per rolling window W in ROLLING_WINDOWS, and per side (home/away) of the
match being featured:
  <side>_form_pts_last{W}   mean points (3/1/0) over the team's last W
                            matches before this one
  <side>_form_gf_last{W}    mean goals scored in those matches
  <side>_form_ga_last{W}    mean goals conceded in those matches
  <side>_form_gd_last{W}    gf - ga
  <side>_form_n_last{W}     how many of the W slots actually have data
                            (< W for a team early in its history; lets
                            any consumer apply its own minimum-sample
                            threshold instead of baking one in here)
All NaN (except *_n, which is 0) for a team's first-ever match in the data.

Deliberately goals/points only: shots, corners, cards etc. appear in
football-data.co.uk files but the ingest pipeline does not store them
(domain Match has no columns for them), so pulling those in is an ingest
schema change, not a features-only change — out of scope here.
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from footpred.ml.features.base import FeatureContext, register_feature_group

ROLLING_WINDOWS: List[int] = [5, 10]


def _build_appearances(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (match, team) — the long shape rolling form is computed
    over. Two rows per match: the home team's appearance and the away
    team's appearance, each carrying that team's own goals-for/against."""
    home = pd.DataFrame({
        "match_id": df["match_id"], "team_id": df["home_team_id"],
        "match_date": df["match_date"],
        "gf": df["ft_home"].astype(float), "ga": df["ft_away"].astype(float),
        "side": "home",
    })
    away = pd.DataFrame({
        "match_id": df["match_id"], "team_id": df["away_team_id"],
        "match_date": df["match_date"],
        "gf": df["ft_away"].astype(float), "ga": df["ft_home"].astype(float),
        "side": "away",
    })
    appearances = pd.concat([home, away], ignore_index=True)
    appearances["points"] = np.select(
        [appearances["gf"] > appearances["ga"], appearances["gf"] == appearances["ga"]],
        [3.0, 1.0], default=0.0,
    )
    return appearances


class TeamFormFeatureGroup:
    name = "team_form"
    version = "1.0"

    def build(self, ctx: FeatureContext) -> pd.DataFrame:
        df = ctx.matches
        appearances = _build_appearances(df)
        # chronological order per team; match_id tiebreaks same-date rows
        # deterministically (mirrors GroupFractionSplit's tiebreak).
        appearances = appearances.sort_values(
            ["team_id", "match_date", "match_id"]
        ).reset_index(drop=True)

        by_team = appearances.groupby("team_id", sort=False)
        appearances["_pts_prior"] = by_team["points"].shift(1)
        appearances["_gf_prior"] = by_team["gf"].shift(1)
        appearances["_ga_prior"] = by_team["ga"].shift(1)

        prior_cols = ["_pts_prior", "_gf_prior", "_ga_prior"]
        for w in ROLLING_WINDOWS:
            roll = (appearances.groupby("team_id")[prior_cols]
                    .rolling(window=w, min_periods=1).mean()
                    .reset_index(level=0, drop=True))
            appearances[f"form_pts_last{w}"] = roll["_pts_prior"]
            appearances[f"form_gf_last{w}"] = roll["_gf_prior"]
            appearances[f"form_ga_last{w}"] = roll["_ga_prior"]
            appearances[f"form_gd_last{w}"] = (
                appearances[f"form_gf_last{w}"] - appearances[f"form_ga_last{w}"])
            appearances[f"form_n_last{w}"] = (
                appearances.groupby("team_id")["_pts_prior"]
                .rolling(window=w, min_periods=1).count()
                .reset_index(level=0, drop=True))

        form_cols = [f"form_{stat}_last{w}"
                     for w in ROLLING_WINDOWS
                     for stat in ("pts", "gf", "ga", "gd", "n")]

        home_out = appearances[appearances["side"] == "home"].set_index("match_id")[form_cols]
        home_out.columns = [f"home_{c}" for c in home_out.columns]
        away_out = appearances[appearances["side"] == "away"].set_index("match_id")[form_cols]
        away_out.columns = [f"away_{c}" for c in away_out.columns]
        return home_out.join(away_out, how="outer")


register_feature_group(TeamFormFeatureGroup())
