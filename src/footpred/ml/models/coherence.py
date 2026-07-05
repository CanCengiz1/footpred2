"""Cross-market coherence: whether the O/U-2.5 market's price is consistent
with what the 1x2 market's implied scoreline distribution predicts, under the
audited Dixon-Coles tau correction and each league's leakage-safe fitted rho.

    incoherence_ou25 = actual market P(over 2.5) - 1x2-implied P(over 2.5)

This is the provisionally-promoted signal from the corrected confirmatory
milestone (see docs/RESEARCH_RETROSPECTIVE.md, "Corrected confirmatory
1x2-coherence milestone"). Reimplemented here as a reusable, tested module --
the original milestone's computation was ad hoc analysis code that was never
committed, a reproducibility gap this module closes (see docs/VISION.md).

Implied (lambda, mu) are backed out from the market's own de-vigged 1x2
probabilities by root-finding under the tau-adjusted independent-Poisson
model -- deliberately not assuming rho=0, which the original (superseded)
diagnostic did. rho itself is fit once per league on training-window goals
history only (DixonColesModel, no odds needed) and reused for every match in
that league. Unlike draw_residual's team-specific leave-one-out construction,
rho is a single scoring-environment-level parameter, not specific to any one
match's own outcome -- using a match's own already-public, pre-kickoff market
price to compute that same match's own feature is not leakage, so no
leave-one-out treatment is needed here.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import root
from scipy.special import gammaln

from footpred.domain.entities import Bookmaker
from footpred.ml.models.dixon_coles import DixonColesModel, _tau

COHERENCE_COLS = ["incoherence_ou25"]
MAX_GOALS = 10


def _grid_probs(lam: float, mu: float, rho: float, max_goals: int = MAX_GOALS
                 ) -> Tuple[float, float, float, float]:
    """(home, draw, away, over_2.5) probabilities implied by a raw
    (lambda, mu, rho) triple -- the same tau-adjusted independent-Poisson
    construction as DixonColesModel.score_matrix, but starting from
    market-implied expected goals directly rather than a fitted team's
    attack/defense parameters."""
    xs = np.arange(max_goals + 1)
    log_px = xs * math.log(lam) - lam - gammaln(xs + 1)
    log_py = xs * math.log(mu) - mu - gammaln(xs + 1)
    px, py = np.exp(log_px), np.exp(log_py)
    xx, yy = np.meshgrid(xs, xs, indexing="ij")
    grid = np.outer(px, py) * _tau(xx, yy, lam, mu, rho)
    grid = np.clip(grid, 0.0, None)
    grid = grid / grid.sum()
    home = float(grid[xx > yy].sum())
    draw = float(grid[xx == yy].sum())
    away = float(grid[xx < yy].sum())
    over = float(grid[(xx + yy) > 2].sum())
    return home, draw, away, over


def _solve_lambda_mu(p_home: float, p_draw: float, rho: float,
                      max_goals: int = MAX_GOALS) -> Optional[Tuple[float, float]]:
    """Recovers (lambda, mu) such that the tau-adjusted grid reproduces the
    target 1x2 probabilities exactly (2 equations -- home, draw -- for 2
    unknowns; away follows since the three sum to 1). Optimizes in log-space
    so lambda, mu stay positive by construction. Returns None if the solver
    doesn't converge or lands on a degenerate (non-finite/non-positive) point,
    rather than propagating a bad value silently."""
    def residual(z):
        lam, mu = np.exp(z)
        h, d, _, _ = _grid_probs(lam, mu, rho, max_goals)
        return [h - p_home, d - p_draw]

    sol = root(residual, x0=np.log([1.3, 1.1]), method="hybr")
    if not sol.success:
        return None
    lam, mu = np.exp(sol.x)
    if not (np.isfinite(lam) and np.isfinite(mu)) or lam <= 0 or mu <= 0:
        return None
    return float(lam), float(mu)


def compute_coherence_features(
    frame: pd.DataFrame, train_mask: pd.Series,
    xi: float = 0.001, devig_method: str = "shin",
    bookmaker: str = Bookmaker.BET365.value,
) -> pd.DataFrame:
    """frame: needs league_key, home_team_id, away_team_id, ft_home, ft_away,
    match_date (to fit rho) plus the de-vigged 1x2 and O/U-2.5 columns for
    ``bookmaker``/``devig_method``. train_mask: boolean Series aligned to
    frame.index, True for this split's training rows.

    Returns a frame (same index as ``frame``) with ``incoherence_ou25`` --
    NaN wherever the required odds columns are absent entirely, rho couldn't
    be fit for that league/split, the row is missing any of the three needed
    odds values, or the root-find didn't converge for that match. rho is fit
    once per league on train_mask rows only and applied to every row (train
    and test) in that league -- see module docstring for why this doesn't
    need draw_residual's leave-one-out treatment.
    """
    out = pd.DataFrame(index=frame.index, columns=COHERENCE_COLS, dtype=float)

    home_col = f"devig_1x2_home_{bookmaker}_{devig_method}"
    draw_col = f"devig_1x2_draw_{bookmaker}_{devig_method}"
    over_col = f"devig_ou_2_5_over_{bookmaker}_{devig_method}"
    required = [home_col, draw_col, over_col]
    if any(c not in frame.columns for c in required):
        return out  # required odds not present at all -> all-NaN, no crash

    for league, league_frame in frame.groupby("league_key"):
        league_train_mask = train_mask.loc[league_frame.index]
        train_rows = league_frame[league_train_mask]
        if train_rows.empty:
            continue

        try:
            model = DixonColesModel(xi=xi)
            model.fit(train_rows[["home_team_id", "away_team_id", "ft_home", "ft_away", "match_date"]])
        except ValueError:
            continue  # e.g. fewer than 2 distinct teams in this league's training window
        rho = model.rho_

        for idx, row in league_frame.iterrows():
            p_home, p_draw, p_over = row[home_col], row[draw_col], row[over_col]
            if pd.isna(p_home) or pd.isna(p_draw) or pd.isna(p_over):
                continue
            solved = _solve_lambda_mu(p_home, p_draw, rho)
            if solved is None:
                continue
            lam, mu = solved
            _, _, _, implied_over = _grid_probs(lam, mu, rho)
            out.loc[idx, "incoherence_ou25"] = p_over - implied_over

    return out
