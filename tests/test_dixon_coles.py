import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from footpred.domain.entities import League, Match, MatchStatus, Team
from footpred.infra.memory import InMemoryUnitOfWork
from footpred.infra.read_models import InMemoryMatchOddsReader
from footpred.ml.backtest.runner import BacktestRunner
from footpred.ml.datasets import DatasetBuilder
from footpred.ml.models.dixon_coles import DixonColesModel, DixonColesPredictor, _tau
from footpred.ml.splits import GroupFractionSplit


# --------------------------- pure math, no fitting -------------------------- #

def test_tau_is_one_away_from_the_four_special_cells():
    assert _tau(2, 3, lam=1.5, mu=1.2, rho=0.15) == 1.0
    assert _tau(5, 0, lam=1.5, mu=1.2, rho=0.15) == 1.0


def test_tau_matches_hand_computed_values_on_special_cells():
    lam, mu, rho = 1.4, 0.9, 0.15
    assert math.isclose(_tau(0, 0, lam, mu, rho), 1 - lam * mu * rho, abs_tol=1e-12)
    assert math.isclose(_tau(1, 0, lam, mu, rho), 1 + lam * rho, abs_tol=1e-12)
    assert math.isclose(_tau(0, 1, lam, mu, rho), 1 + mu * rho, abs_tol=1e-12)
    assert math.isclose(_tau(1, 1, lam, mu, rho), 1 - rho, abs_tol=1e-12)


def _hand_set_model(attack, defense, home_adv, rho, max_goals=10):
    """Construct a fitted-looking model by hand, skipping .fit() entirely —
    isolates the score_matrix/predict_* math from the optimizer."""
    m = DixonColesModel(max_goals=max_goals)
    m.team_ids_ = list(range(len(attack)))
    m.team_index_ = {t: i for i, t in enumerate(m.team_ids_)}
    m.attack_ = np.array(attack, dtype=float)
    m.defense_ = np.array(defense, dtype=float)
    m.home_advantage_ = home_adv
    m.rho_ = rho
    return m


def test_probabilities_sum_to_one_for_both_markets():
    m = _hand_set_model(attack=[0.3, -0.2], defense=[-0.1, 0.4], home_adv=0.25, rho=0.1)
    grid = m.score_matrix(0, 1)
    assert math.isclose(grid.sum(), 1.0, abs_tol=1e-9)
    p1x2 = m.predict_1x2(0, 1)
    assert math.isclose(sum(p1x2), 1.0, abs_tol=1e-9)
    pou = m.predict_ou25(0, 1)
    assert math.isclose(sum(pou), 1.0, abs_tol=1e-9)


def test_rho_zero_reduces_to_independent_poisson():
    attack, defense, home_adv = [0.3, -0.2], [-0.1, 0.4], 0.25
    m = _hand_set_model(attack, defense, home_adv, rho=0.0)
    grid = m.score_matrix(0, 1)

    lam = math.exp(attack[0] + defense[1] + home_adv)
    mu = math.exp(attack[1] + defense[0])
    from scipy.stats import poisson
    expected = np.outer(poisson.pmf(np.arange(11), lam), poisson.pmf(np.arange(11), mu))
    expected = expected / expected.sum()  # same truncation-at-10 renormalization
    np.testing.assert_allclose(grid, expected, atol=1e-10)


def test_stronger_attack_increases_win_probability():
    # team 0 much stronger attack than team 1; both average defense
    strong = _hand_set_model(attack=[1.2, -1.2], defense=[0.0, 0.0], home_adv=0.2, rho=0.0)
    p_home_win, _, p_away_win = strong.predict_1x2(0, 1)
    assert p_home_win > 0.7
    assert p_home_win > p_away_win


# --------------------------- MLE parameter recovery ------------------------- #

def _simulate_round_robin(rng, true_attack, true_defense, true_home_adv, true_rho,
                           n_rounds, max_goals=15):
    """Generate synthetic match results from KNOWN ground-truth parameters by
    sampling directly from the Dixon-Coles adjusted score distribution."""
    from footpred.ml.models.dixon_coles import _tau as tau_fn
    n_teams = len(true_attack)
    xs = np.arange(max_goals + 1)
    rows = []
    for _ in range(n_rounds):
        for i in range(n_teams):
            for j in range(n_teams):
                if i == j:
                    continue
                lam = math.exp(true_attack[i] + true_defense[j] + true_home_adv)
                mu = math.exp(true_attack[j] + true_defense[i])
                log_px = xs * math.log(lam) - lam - _lgamma_vec(xs)
                log_py = xs * math.log(mu) - mu - _lgamma_vec(xs)
                px, py = np.exp(log_px), np.exp(log_py)
                xx, yy = np.meshgrid(xs, xs, indexing="ij")
                grid = np.outer(px, py) * tau_fn(xx, yy, lam, mu, true_rho)
                grid = np.clip(grid, 0.0, None)
                grid = grid / grid.sum()
                flat_idx = rng.choice(grid.size, p=grid.ravel())
                fh, fa = np.unravel_index(flat_idx, grid.shape)
                rows.append({"home_team_id": i, "away_team_id": j,
                             "ft_home": int(fh), "ft_away": int(fa)})
    return pd.DataFrame(rows)


def _lgamma_vec(k):
    from scipy.special import gammaln
    return gammaln(k + 1)


@pytest.mark.parametrize("true_rho", [0.0, -0.15])
def test_mle_recovers_known_ground_truth_parameters(true_rho):
    rng = np.random.default_rng(42)
    true_attack = np.array([0.5, 0.2, -0.1, -0.3, 0.0, -0.4, 0.3, -0.2])
    true_defense = np.array([-0.3, 0.1, 0.2, 0.4, -0.1, 0.3, -0.2, 0.0])
    true_home_adv = 0.28

    matches = _simulate_round_robin(rng, true_attack, true_defense, true_home_adv,
                                     true_rho, n_rounds=60)
    model = DixonColesModel().fit(matches)

    # predictions (lambda/mu), not raw alpha/beta, are the identifiable
    # quantities -- compare those directly against the true generating values
    n_teams = len(true_attack)
    lam_errors, mu_errors = [], []
    for i in range(n_teams):
        for j in range(n_teams):
            if i == j:
                continue
            true_lam = math.exp(true_attack[i] + true_defense[j] + true_home_adv)
            true_mu = math.exp(true_attack[j] + true_defense[i])
            fitted_lam = math.exp(model.attack_[i] + model.defense_[j] + model.home_advantage_)
            fitted_mu = math.exp(model.attack_[j] + model.defense_[i])
            lam_errors.append(abs(fitted_lam - true_lam) / true_lam)
            mu_errors.append(abs(fitted_mu - true_mu) / true_mu)

    assert np.mean(lam_errors) < 0.20
    assert np.mean(mu_errors) < 0.20
    # rho is inherently the weakest-identified parameter (it only touches 4
    # of the score grid's cells), so its recovery tolerance is looser than
    # lambda/mu's -- this still catches a wrong sign or a badly broken tau.
    assert abs(model.rho_ - true_rho) < 0.15


# --------------------------- multi-league predictor wrapper ----------------- #

def _synthetic_league_matches(league_key, team_ids, n_rounds, rng, attack, defense, home_adv=0.2):
    """Plausible non-degenerate scorelines for a league -- not a ground-truth
    recovery check (that's covered above), just enough signal for the
    per-league isolation and abstention tests below."""
    rows = []
    for _ in range(n_rounds):
        for i, home in enumerate(team_ids):
            for j, away in enumerate(team_ids):
                if home == away:
                    continue
                lam = math.exp(attack[i] + defense[j] + home_adv)
                mu = math.exp(attack[j] + defense[i])
                rows.append({"league_key": league_key, "home_team_id": home,
                             "away_team_id": away,
                             "ft_home": int(rng.poisson(lam)), "ft_away": int(rng.poisson(mu))})
    return pd.DataFrame(rows)


def test_per_league_isolation_even_with_shared_team_ids():
    # both leagues reuse the SAME team_id values on purpose -- proves
    # isolation isn't accidentally relying on team_ids being disjoint
    team_ids = [1, 2, 3, 4]
    rng = np.random.default_rng(7)
    high_scoring = _synthetic_league_matches("L1", team_ids, n_rounds=20, rng=rng,
                                              attack=[1.0] * 4, defense=[0.0] * 4)
    low_scoring = _synthetic_league_matches("L2", team_ids, n_rounds=20, rng=rng,
                                            attack=[-1.0] * 4, defense=[0.0] * 4)
    train = pd.concat([high_scoring, low_scoring], ignore_index=True)

    predictor = DixonColesPredictor().fit(train)
    assert set(predictor._models) == {"L1", "L2"}
    # attack_[0] alone isn't meaningful here (it's always 0 -- the fixed
    # reference team); the identifiable, prediction-relevant quantity is the
    # fitted lambda for a given matchup, which must differ sharply between
    # the two leagues despite sharing team_id 1 vs 2 in both
    m1, m2 = predictor._models["L1"], predictor._models["L2"]
    lam1 = math.exp(m1.attack_[0] + m1.defense_[1] + m1.home_advantage_)
    lam2 = math.exp(m2.attack_[0] + m2.defense_[1] + m2.home_advantage_)
    assert lam1 > 3 * lam2  # true ratio is exp(1.2)/exp(-0.8) ~= 7.4

    X = pd.DataFrame({"league_key": ["L1", "L2"], "home_team_id": [1, 1], "away_team_id": [2, 2]})
    probs = predictor.predict_proba("1x2", X)
    assert np.isclose(probs.loc[0].sum(), 1.0)
    assert np.isclose(probs.loc[1].sum(), 1.0)


def test_abstains_on_unseen_team():
    train = _synthetic_league_matches("L1", [1, 2, 3, 4], n_rounds=10,
                                       rng=np.random.default_rng(1),
                                       attack=[0.2, -0.1, 0.0, 0.1], defense=[0.0] * 4)
    predictor = DixonColesPredictor().fit(train)
    X = pd.DataFrame({"league_key": ["L1"], "home_team_id": [999], "away_team_id": [1]})
    probs = predictor.predict_proba("1x2", X)
    assert probs.iloc[0].isna().all()


def test_abstains_on_unseen_league():
    train = _synthetic_league_matches("L1", [1, 2, 3, 4], n_rounds=10,
                                       rng=np.random.default_rng(1),
                                       attack=[0.2, -0.1, 0.0, 0.1], defense=[0.0] * 4)
    predictor = DixonColesPredictor().fit(train)
    X = pd.DataFrame({"league_key": ["L9"], "home_team_id": [1], "away_team_id": [2]})
    probs = predictor.predict_proba("1x2", X)
    assert probs.iloc[0].isna().all()


def test_ou25_market_supported():
    train = _synthetic_league_matches("L1", [1, 2, 3, 4], n_rounds=10,
                                       rng=np.random.default_rng(1),
                                       attack=[0.2, -0.1, 0.0, 0.1], defense=[0.0] * 4)
    predictor = DixonColesPredictor().fit(train)
    X = pd.DataFrame({"league_key": ["L1"], "home_team_id": [1], "away_team_id": [2]})
    probs = predictor.predict_proba("ou_2.5", X)
    assert list(probs.columns) == ["over", "under"]
    assert np.isclose(probs.iloc[0].sum(), 1.0)


# --------------------------- end-to-end harness wiring ---------------------- #

def test_dixon_coles_plugs_into_unmodified_backtest_runner():
    """Fits on a built dataset's train split and scores through
    BacktestRunner exactly as MarketBaseline does -- this file (runner.py)
    is untouched by Pass B; that's the actual point of the Predictor
    protocol design."""
    rng = np.random.default_rng(3)
    uow = InMemoryUnitOfWork()
    league = uow.leagues.add(League(id=None, canonical_key="toy_league", name="Toy League"))
    team_ids = {}

    def team_id(name):
        if name not in team_ids:
            t = uow.teams.add(Team(id=None, canonical_name=name, normalized_key=name.lower()))
            team_ids[name] = t.id
        return team_ids[name]

    names = ["A", "B", "C", "D", "E", "F"]
    attack = rng.normal(0, 0.4, size=len(names))
    defense = rng.normal(0, 0.4, size=len(names))
    d = date(2024, 8, 1)
    for _ in range(15):  # 15 rounds x 6 teams x 5 opponents = 450 matches
        for i, home in enumerate(names):
            for j, away in enumerate(names):
                if i == j:
                    continue
                lam = math.exp(attack[i] + defense[j] + 0.25)
                mu = math.exp(attack[j] + defense[i])
                uow.matches.add(Match(
                    id=None, league_id=league.id, home_team_id=team_id(home),
                    away_team_id=team_id(away), match_date=d, kickoff_utc=None,
                    ht_home=None, ht_away=None,
                    ft_home=int(rng.poisson(lam)), ft_away=int(rng.poisson(mu)),
                    status=MatchStatus.COMPLETED, import_id=None,
                ))
                d += timedelta(days=1)

    reader = InMemoryMatchOddsReader(uow)
    frame, _ = DatasetBuilder(reader, feature_groups=["odds_core", "team_form"],
                               split=GroupFractionSplit(0.7)).build()

    predictor = DixonColesPredictor().fit(frame[frame["split"] == "train"])
    report = BacktestRunner(value_threshold=0.02).run(frame, predictor, "1x2")

    assert report.n_rows_scored > 0
    assert report.log_loss > 0
    assert 0 < report.brier < 2
    assert report.calibration["n_points"] == report.n_rows_scored * 3
