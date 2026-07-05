from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from footpred.ml.models.coherence import (
    COHERENCE_COLS, _grid_probs, _solve_lambda_mu, compute_coherence_features,
)
from footpred.ml.models.dixon_coles import DixonColesModel


def _toy_matches(n_teams=4, n_rounds=3, seed=0):
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


ODDS_COLS = {
    "home": "devig_1x2_home_bet365_shin",
    "draw": "devig_1x2_draw_bet365_shin",
    "away": "devig_1x2_away_bet365_shin",
    "over": "devig_ou_2_5_over_bet365_shin",
}


def _fake_fit(rho):
    def fit(self, matches):
        self.rho_ = rho
        return self
    return fit


# --------------------------- shape / missing columns --------------------- #

def test_missing_required_odds_columns_returns_all_nan_no_crash():
    frame = _toy_matches()
    train_mask = pd.Series(True, index=frame.index)
    out = compute_coherence_features(frame, train_mask)
    assert list(out.columns) == COHERENCE_COLS
    assert out.index.equals(frame.index)
    assert out["incoherence_ou25"].isna().all()


def test_missing_per_row_odds_gives_nan_for_that_row_only():
    frame = _toy_matches()
    train_mask = pd.Series(True, index=frame.index)
    train_mask.iloc[-6:] = False
    frame[ODDS_COLS["home"]] = 0.45
    frame[ODDS_COLS["draw"]] = 0.27
    frame[ODDS_COLS["away"]] = 0.28
    frame[ODDS_COLS["over"]] = 0.55
    missing_idx = frame.index[0]
    frame.loc[missing_idx, ODDS_COLS["over"]] = np.nan

    with patch.object(DixonColesModel, "fit", _fake_fit(-0.03)):
        out = compute_coherence_features(frame, train_mask)

    assert np.isnan(out.loc[missing_idx, "incoherence_ou25"])
    assert out["incoherence_ou25"].notna().sum() > 0


# --------------------------- round-trip correctness ---------------------- #

def test_recovers_near_zero_incoherence_when_market_matches_implied_grid():
    frame = _toy_matches()
    train_mask = pd.Series(True, index=frame.index)
    train_mask.iloc[-6:] = False

    rho = -0.03
    lam, mu = 1.4, 1.05
    p_home, p_draw, p_away, p_over = _grid_probs(lam, mu, rho)
    frame[ODDS_COLS["home"]] = p_home
    frame[ODDS_COLS["draw"]] = p_draw
    frame[ODDS_COLS["away"]] = p_away
    frame[ODDS_COLS["over"]] = p_over  # exactly matches the implied grid

    with patch.object(DixonColesModel, "fit", _fake_fit(rho)):
        out = compute_coherence_features(frame, train_mask)

    valid = out["incoherence_ou25"].dropna()
    assert not valid.empty
    assert np.allclose(valid, 0.0, atol=1e-6)


def test_deliberate_incoherence_recovered_within_tolerance():
    frame = _toy_matches()
    train_mask = pd.Series(True, index=frame.index)
    train_mask.iloc[-6:] = False

    rho = -0.03
    lam, mu = 1.4, 1.05
    p_home, p_draw, p_away, p_over = _grid_probs(lam, mu, rho)
    injected_gap = 0.05
    frame[ODDS_COLS["home"]] = p_home
    frame[ODDS_COLS["draw"]] = p_draw
    frame[ODDS_COLS["away"]] = p_away
    frame[ODDS_COLS["over"]] = p_over + injected_gap

    with patch.object(DixonColesModel, "fit", _fake_fit(rho)):
        out = compute_coherence_features(frame, train_mask)

    valid = out["incoherence_ou25"].dropna()
    assert not valid.empty
    assert np.allclose(valid, injected_gap, atol=1e-3)


# --------------------------- test rows use plain (no leave-one-out) ------ #

def test_test_rows_also_scored_using_train_fitted_rho():
    frame = _toy_matches()
    train_mask = pd.Series(True, index=frame.index)
    train_mask.iloc[-6:] = False
    rho = -0.03
    frame[ODDS_COLS["home"]] = 0.45
    frame[ODDS_COLS["draw"]] = 0.27
    frame[ODDS_COLS["away"]] = 0.28
    frame[ODDS_COLS["over"]] = 0.55

    with patch.object(DixonColesModel, "fit", _fake_fit(rho)):
        out = compute_coherence_features(frame, train_mask)

    test_rows = out.loc[~train_mask.to_numpy()]
    assert test_rows["incoherence_ou25"].notna().all()


# --------------------------- graceful failure paths ----------------------- #

def test_dc_fit_failure_for_a_league_gives_nan_not_crash():
    frame = _toy_matches()
    train_mask = pd.Series(True, index=frame.index)
    frame[ODDS_COLS["home"]] = 0.4
    frame[ODDS_COLS["draw"]] = 0.3
    frame[ODDS_COLS["away"]] = 0.3
    frame[ODDS_COLS["over"]] = 0.5

    with patch.object(DixonColesModel, "fit", side_effect=ValueError("not enough teams")):
        out = compute_coherence_features(frame, train_mask)

    assert out["incoherence_ou25"].isna().all()


def test_solve_lambda_mu_returns_none_on_non_convergence():
    fake_result = MagicMock(success=False)
    with patch("footpred.ml.models.coherence.root", return_value=fake_result):
        assert _solve_lambda_mu(0.4, 0.3, -0.03) is None


def test_solve_lambda_mu_recovers_known_values():
    rho = -0.02
    lam, mu = 1.2, 0.9
    p_home, p_draw, _, _ = _grid_probs(lam, mu, rho)
    solved = _solve_lambda_mu(p_home, p_draw, rho)
    assert solved is not None
    got_lam, got_mu = solved
    assert np.isclose(got_lam, lam, atol=1e-4)
    assert np.isclose(got_mu, mu, atol=1e-4)
