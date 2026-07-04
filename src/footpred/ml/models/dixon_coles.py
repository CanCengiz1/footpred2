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
    scorelines. x, y may be arrays; lam, mu, rho broadcast against them.

    Matches Dixon & Coles (1997) exactly: tau(0,1) uses lam (home expected
    goals), tau(1,0) uses mu (away expected goals) -- this cross-assignment
    is not a typo, it's the paper's actual formula, confirmed against the
    dashee87 and penaltyblog reference implementations. An earlier version
    of this function had lam/mu swapped on these two cells."""
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
        1.0 + mu * rho,
        1.0 + lam * rho,
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


def _time_weights(match_dates: pd.Series, xi: float, reference_date=None) -> np.ndarray:
    """Dixon & Coles (1997) time-decay weight per match: exp(-xi * days_elapsed),
    days_elapsed = reference_date - match_date. xi=0.0 -> every match weighted
    1.0 regardless of date (no decay). reference_date defaults to the latest
    date in match_dates (the fit's "as of today" date), so the most recent
    training match always gets weight 1.0 and older ones are progressively
    down-weighted."""
    if xi == 0.0:
        return np.ones(len(match_dates))
    dates = pd.to_datetime(match_dates)
    ref = pd.to_datetime(reference_date) if reference_date is not None else dates.max()
    days = (ref - dates).dt.days.to_numpy(dtype=float)
    return np.exp(-xi * days)


def _neg_log_likelihood(theta, home_idx, away_idx, x, y, n_teams, weights) -> float:
    attack, defense, home_adv, rho = _unpack(theta, n_teams)
    lam = np.exp(attack[home_idx] + defense[away_idx] + home_adv)
    mu = np.exp(attack[away_idx] + defense[home_idx])
    logpmf_x = x * np.log(lam) - lam - gammaln(x + 1)
    logpmf_y = y * np.log(mu) - mu - gammaln(y + 1)
    tau = np.clip(_tau(x, y, lam, mu, rho), 1e-10, None)
    return -float(np.sum(weights * (np.log(tau) + logpmf_x + logpmf_y)))


class DixonColesModel:
    """Single-league Dixon-Coles model. Fit on one competition's historical
    results; predicts full scoreline distributions for any (home, away)
    pair among the teams seen during fit.

    xi: time-decay rate (Dixon & Coles 1997's exponential down-weighting of
    older matches). 0.0 (default) disables decay entirely -- every match in
    the training window is weighted equally, matching the module's original
    behavior. xi > 0 requires a ``match_date`` column in ``matches``."""

    def __init__(self, max_goals: int = 10, xi: float = 0.0):
        self.max_goals = max_goals
        self.xi = xi
        self.team_ids_: List[int] = []
        self.team_index_: Dict[int, int] = {}
        self.attack_: np.ndarray = np.array([])
        self.defense_: np.ndarray = np.array([])
        self.home_advantage_: float = 0.0
        self.rho_: float = 0.0
        self.converged_: bool = False
        self.n_matches_: int = 0
        self.reference_date_ = None

    def fit(self, matches: pd.DataFrame) -> "DixonColesModel":
        """matches: columns home_team_id, away_team_id, ft_home, ft_away —
        one league's completed matches. Also needs match_date if self.xi > 0."""
        if self.xi > 0.0 and "match_date" not in matches.columns:
            raise ValueError(
                "xi > 0 requires a 'match_date' column to compute time-decay weights")

        teams = sorted(set(matches["home_team_id"]) | set(matches["away_team_id"]))
        n_teams = len(teams)
        if n_teams < 2:
            raise ValueError("need at least 2 distinct teams to fit Dixon-Coles")
        index = {t: i for i, t in enumerate(teams)}
        home_idx = matches["home_team_id"].map(index).to_numpy()
        away_idx = matches["away_team_id"].map(index).to_numpy()
        x = matches["ft_home"].to_numpy(dtype=float)
        y = matches["ft_away"].to_numpy(dtype=float)

        if self.xi > 0.0:
            weights = _time_weights(matches["match_date"], self.xi)
            self.reference_date_ = pd.to_datetime(matches["match_date"]).max()
        else:
            weights = np.ones(len(matches))
            self.reference_date_ = None

        n_params = 2 * n_teams + 1
        x0 = np.zeros(n_params)
        x0[2 * n_teams - 1] = 0.1  # mild positive home-advantage prior
        bounds = [(-3.0, 3.0)] * (2 * n_teams - 1) + [(-3.0, 3.0)] + [(-0.9, 0.9)]

        result = minimize(_neg_log_likelihood, x0,
                           args=(home_idx, away_idx, x, y, n_teams, weights),
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

    def __init__(self, max_goals: int = 10, xi: float = 0.0):
        self.max_goals = max_goals
        self.xi = xi
        self.name = "DixonColes" if xi == 0.0 else f"DixonColes[xi={xi}]"
        self._models: Dict[str, DixonColesModel] = {}

    def fit(self, train: pd.DataFrame) -> "DixonColesPredictor":
        """train: columns league_key, home_team_id, away_team_id, ft_home,
        ft_away — typically the 'train' split of a built dataset. Also needs
        match_date if self.xi > 0."""
        self._models = {
            league_key: DixonColesModel(max_goals=self.max_goals, xi=self.xi).fit(group)
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
