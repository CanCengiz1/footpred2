"""Dixon-Coles (1997): the classic attack/defense/home-advantage goal model,
with the low-score correlation correction that distinguishes it from a
plain independent-Poisson scoreline model.

For a match between home team i and away team j:
    lambda = exp(attack_i + defense_j + home_advantage)   # home goals
    mu     = exp(attack_j + defense_i)                    # away goals
    P(X=x, Y=y) = tau(x, y, lambda, mu, rho) * Poisson(x; lambda) * Poisson(y; mu)

tau adjusts the four low-score cells (0-0, 1-0, 0-1, 1-1) via a single
correlation parameter rho, fit jointly with attack/defense/home-advantage
by maximum likelihood. This module is single-league: a competition's teams
share one scoring environment, so attack/defense strengths are only
comparable within one league's fit (see DixonColesPredictor for the
multi-league dispatch).

Identifiability: attack and defense are only identified up to a constant
shift (attack_i + c, defense_i - c leaves every lambda/mu unchanged for
every i), so one team's attack parameter is fixed at 0 as an arbitrary
reference point. This is cosmetic — predictions do not depend on the
choice of reference team.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln


def _tau(x, y, lam, mu, rho):
    """Low-score correction factor. 1.0 everywhere except the four cells
    where a plain independent-Poisson model is known to misfit football
    scorelines. x, y may be arrays; lam, mu, rho broadcast against them."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    conditions = [
        (x == 0) & (y == 0),
        (x == 1) & (y == 0),
        (x == 0) & (y == 1),
        (x == 1) & (y == 1),
    ]
    choices = [
        1.0 - lam * mu * rho,
        1.0 + lam * rho,
        1.0 + mu * rho,
        1.0 - rho,
    ]
    return np.select(conditions, choices, default=1.0)


def _unpack(theta: np.ndarray, n_teams: int) -> Tuple[np.ndarray, np.ndarray, float, float]:
    """theta = [attack_1..attack_{T-1}, defense_0..defense_{T-1}, home_adv, rho].
    attack_0 is fixed at 0.0 (identifiability reference, see module docstring)."""
    attack = np.empty(n_teams)
    attack[0] = 0.0
    attack[1:] = theta[: n_teams - 1]
    defense = theta[n_teams - 1: 2 * n_teams - 1]
    home_adv = theta[2 * n_teams - 1]
    rho = theta[2 * n_teams]
    return attack, defense, float(home_adv), float(rho)


def _neg_log_likelihood(theta, home_idx, away_idx, x, y, n_teams) -> float:
    attack, defense, home_adv, rho = _unpack(theta, n_teams)
    lam = np.exp(attack[home_idx] + defense[away_idx] + home_adv)
    mu = np.exp(attack[away_idx] + defense[home_idx])
    logpmf_x = x * np.log(lam) - lam - gammaln(x + 1)
    logpmf_y = y * np.log(mu) - mu - gammaln(y + 1)
    tau = np.clip(_tau(x, y, lam, mu, rho), 1e-10, None)
    return -float(np.sum(np.log(tau) + logpmf_x + logpmf_y))


class DixonColesModel:
    """Single-league Dixon-Coles model. Fit on one competition's historical
    results; predicts full scoreline distributions for any (home, away)
    pair among the teams seen during fit."""

    def __init__(self, max_goals: int = 10):
        self.max_goals = max_goals
        self.team_ids_: List[int] = []
        self.team_index_: Dict[int, int] = {}
        self.attack_: np.ndarray = np.array([])
        self.defense_: np.ndarray = np.array([])
        self.home_advantage_: float = 0.0
        self.rho_: float = 0.0
        self.converged_: bool = False
        self.n_matches_: int = 0

    def fit(self, matches: pd.DataFrame) -> "DixonColesModel":
        """matches: columns home_team_id, away_team_id, ft_home, ft_away —
        one league's completed matches."""
        teams = sorted(set(matches["home_team_id"]) | set(matches["away_team_id"]))
        n_teams = len(teams)
        if n_teams < 2:
            raise ValueError("need at least 2 distinct teams to fit Dixon-Coles")
        index = {t: i for i, t in enumerate(teams)}
        home_idx = matches["home_team_id"].map(index).to_numpy()
        away_idx = matches["away_team_id"].map(index).to_numpy()
        x = matches["ft_home"].to_numpy(dtype=float)
        y = matches["ft_away"].to_numpy(dtype=float)

        n_params = 2 * n_teams + 1
        x0 = np.zeros(n_params)
        x0[2 * n_teams - 1] = 0.1  # mild positive home-advantage prior
        bounds = [(-3.0, 3.0)] * (2 * n_teams - 1) + [(-3.0, 3.0)] + [(-0.9, 0.9)]

        result = minimize(_neg_log_likelihood, x0,
                           args=(home_idx, away_idx, x, y, n_teams),
                           method="L-BFGS-B", bounds=bounds)

        attack, defense, home_adv, rho = _unpack(result.x, n_teams)
        self.team_ids_ = teams
        self.team_index_ = index
        self.attack_ = attack
        self.defense_ = defense
        self.home_advantage_ = home_adv
        self.rho_ = rho
        self.converged_ = bool(result.success)
        self.n_matches_ = len(matches)
        return self

    def score_matrix(self, home_team_id, away_team_id) -> np.ndarray:
        """(max_goals+1, max_goals+1) grid; cell [x, y] = P(home=x, away=y).
        Raises KeyError if either team was not seen during fit."""
        hi = self.team_index_[home_team_id]
        ai = self.team_index_[away_team_id]
        lam = math.exp(self.attack_[hi] + self.defense_[ai] + self.home_advantage_)
        mu = math.exp(self.attack_[ai] + self.defense_[hi])
        xs = np.arange(self.max_goals + 1)
        log_px = xs * math.log(lam) - lam - gammaln(xs + 1)
        log_py = xs * math.log(mu) - mu - gammaln(xs + 1)
        px, py = np.exp(log_px), np.exp(log_py)
        xx, yy = np.meshgrid(xs, xs, indexing="ij")
        grid = np.outer(px, py) * _tau(xx, yy, lam, mu, self.rho_)
        # tau is an additive perturbation and does not exactly preserve
        # total probability (a known property of the original formula, see
        # Dixon & Coles 1997); exact renormalization mirrors odds_math.devig.
        grid = np.clip(grid, 0.0, None)
        return grid / grid.sum()

    def predict_1x2(self, home_team_id, away_team_id) -> Tuple[float, float, float]:
        grid = self.score_matrix(home_team_id, away_team_id)
        xs = np.arange(grid.shape[0])
        xx, yy = np.meshgrid(xs, xs, indexing="ij")
        return (float(grid[xx > yy].sum()), float(grid[xx == yy].sum()),
                float(grid[xx < yy].sum()))

    def predict_ou25(self, home_team_id, away_team_id) -> Tuple[float, float]:
        grid = self.score_matrix(home_team_id, away_team_id)
        xs = np.arange(grid.shape[0])
        xx, yy = np.meshgrid(xs, xs, indexing="ij")
        total = xx + yy
        return float(grid[total > 2].sum()), float(grid[total <= 2].sum())


class DixonColesPredictor:
    """Predictor-protocol wrapper: one DixonColesModel per league. A
    competition's teams share one scoring environment (average goals per
    game differs a lot between e.g. a top division and one below it), so
    fitting a single pooled model across leagues would conflate different
    scoring rates — this fits one model per league_key instead. Abstains
    (NaN) for a match whose league wasn't in the training data, or whose
    home/away team wasn't seen within that league's training data — same
    convention as MarketBaseline."""

    def __init__(self, max_goals: int = 10):
        self.max_goals = max_goals
        self.name = "DixonColes"
        self._models: Dict[str, DixonColesModel] = {}

    def fit(self, train: pd.DataFrame) -> "DixonColesPredictor":
        """train: columns league_key, home_team_id, away_team_id, ft_home,
        ft_away — typically the 'train' split of a built dataset."""
        self._models = {
            league_key: DixonColesModel(max_goals=self.max_goals).fit(group)
            for league_key, group in train.groupby("league_key")
        }
        return self

    def predict_proba(self, market: str, X: pd.DataFrame) -> pd.DataFrame:
        if market == "1x2":
            sels, predict = ["home", "draw", "away"], DixonColesModel.predict_1x2
        elif market == "ou_2.5":
            sels, predict = ["over", "under"], DixonColesModel.predict_ou25
        else:
            raise KeyError(f"DixonColesPredictor does not support market {market!r}")

        out = pd.DataFrame(index=X.index, columns=sels, dtype=float)
        for idx, row in X.iterrows():
            model = self._models.get(row["league_key"])
            if model is None:
                continue  # league not fit -> row stays NaN (abstain)
            try:
                out.loc[idx] = predict(model, row["home_team_id"], row["away_team_id"])
            except KeyError:
                continue  # team not seen during fit -> abstain
        return out
