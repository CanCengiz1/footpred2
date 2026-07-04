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
from footpred.ml.models.dixon_coles import (
    DixonColesModel, DixonColesPredictor, _tau, _time_weights,
)
from footpred.ml.splits import GroupFractionSplit


# --------------------------- pure math, no fitting -------------------------- #

def test_tau_is_one_away_from_the_four_special_cells():
    assert _tau(2, 3, lam=1.5, mu=1.2, rho=0.15) == 1.0
    assert _tau(5, 0, lam=1.5, mu=1.2, rho=0.15) == 1.0


def test_tau_matches_hand_computed_values_on_special_cells():
    """Paper-faithful formula (Dixon & Coles 1997): tau(0,1) uses lam (home
    expected goals), tau(1,0) uses mu (away expected goals) -- confirmed
    against the dashee87 and penaltyblog reference implementations."""
    lam, mu, rho = 1.4, 0.9, 0.15
    assert math.isclose(_tau(0, 0, lam, mu, rho), 1 - lam * mu * rho, abs_tol=1e-12)
    assert math.isclose(_tau(1, 0, lam, mu, rho), 1 + mu * rho, abs_tol=1e-12)
    assert math.isclose(_tau(0, 1, lam, mu, rho), 1 + lam * rho, abs_tol=1e-12)
    assert math.isclose(_tau(1, 1, lam, mu, rho), 1 - rho, abs_tol=1e-12)


def test_tau_regression_lambda_mu_not_swapped():
    """Explicit regression test with hardcoded expected values, deliberately
    separate from the hand-computed test above: an earlier version of _tau
    had lam and mu swapped on the (1,0)/(0,1) cells. Because lam and mu are
    usually different (home advantage), that swap changes the numeric
    result, not just a symbolic label -- so this catches it even if a future
    edit to the "hand computed" test above accidentally re-encodes the bug
    by mirroring whatever _tau happens to do.

    lam=2.0, mu=0.5, rho=0.2:
      correct tau(1,0) = 1 + mu*rho = 1 + 0.5*0.2 = 1.10
      correct tau(0,1) = 1 + lam*rho = 1 + 2.0*0.2 = 1.40
      the swapped (buggy) implementation would instead give 1.40 and 1.10
      respectively -- clearly distinguishable, not a coincidental match.
    """
    lam, mu, rho = 2.0, 0.5, 0.2
    assert math.isclose(_tau(1, 0, lam, mu, rho), 1.10, abs_tol=1e-12)
    assert math.isclose(_tau(0, 1, lam, mu, rho), 1.40, abs_tol=1e-12)


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


# --------------------------- time-decay weighting --------------------------- #

def test_time_weights_no_decay_when_xi_zero():
    dates = pd.Series([date(2020, 1, 1), date(2024, 1, 1), date(2015, 6, 1)])
    weights = _time_weights(dates, xi=0.0)
    np.testing.assert_array_equal(weights, np.ones(3))


def test_time_weights_decay_formula():
    ref = date(2024, 1, 1)
    dates = pd.Series([date(2024, 1, 1), date(2023, 1, 2), date(2020, 1, 1)])
    xi = 0.001
    weights = _time_weights(dates, xi=xi, reference_date=ref)
    # day 0 -> weight exactly 1.0
    assert math.isclose(weights[0], 1.0, abs_tol=1e-12)
    expected_days_1 = (ref - dates.iloc[1]).days
    assert math.isclose(weights[1], math.exp(-xi * expected_days_1), rel_tol=1e-9)
    # older date decays further; weights strictly decrease with age
    assert weights[0] > weights[1] > weights[2]


def test_fit_requires_match_date_when_xi_positive():
    matches = pd.DataFrame({
        "home_team_id": [1, 2], "away_team_id": [2, 1],
        "ft_home": [1, 0], "ft_away": [0, 1],
    })
    with pytest.raises(ValueError, match="match_date"):
        DixonColesModel(xi=0.01).fit(matches)


def test_time_decay_tracks_recent_regime_better_than_no_decay():
    """Team 1's attack strength changes partway through the training window
    (strong early, weak later). Team 0 is deliberately left unchanged and
    used only as the fixed identifiability reference (attack_[0] is always
    pinned to 0.0 by construction, see module docstring -- testing on it
    would prove nothing). A model with a large xi should end up closer to
    the RECENT (weak) truth for team 1 than a model with xi=0, which pools
    both regimes equally -- this is the concrete behavior time-decay is
    supposed to buy."""
    rng = np.random.default_rng(11)
    team_ids = [0, 1, 2, 3]
    fixed_defense = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
    home_adv = 0.2

    rows = []
    start = date(2015, 1, 1)
    n_rounds_per_regime = 40
    # early regime: team 1 strong attacker; late regime: team 1 weak attacker
    for regime_idx, team1_attack in enumerate([1.5, -1.5]):
        attack = {0: 0.0, 1: team1_attack, 2: 0.0, 3: 0.0}
        for r in range(n_rounds_per_regime):
            d = start + timedelta(days=(regime_idx * n_rounds_per_regime + r) * 7)
            for i in team_ids:
                for j in team_ids:
                    if i == j:
                        continue
                    lam = math.exp(attack[i] + fixed_defense[j] + home_adv)
                    mu = math.exp(attack[j] + fixed_defense[i])
                    rows.append({"home_team_id": i, "away_team_id": j,
                                 "ft_home": int(rng.poisson(lam)),
                                 "ft_away": int(rng.poisson(mu)),
                                 "match_date": d})
    matches = pd.DataFrame(rows)

    model_no_decay = DixonColesModel(xi=0.0).fit(matches)
    model_decay = DixonColesModel(xi=0.02).fit(matches)  # aggressive decay, ~35-day half-life

    # recent truth: team 1 is now a WEAK attacker (attack=-1.5) relative to
    # the others (attack=0) -- the decayed model's estimate should sit
    # closer to that than the undecayed model's, which is dragged up by the
    # early strong-attacker regime it weights equally.
    i1_decay = model_decay.team_index_[1]
    i1_no_decay = model_no_decay.team_index_[1]
    assert model_decay.attack_[i1_decay] < model_no_decay.attack_[i1_no_decay]


# --------------------------- MLE parameter recovery ------------------------- #

def _simulate_round_robin(rng, true_attack, true_defense, true_home_adv, true_rho,
                           n_rounds, max_goals=15):
    """Generate synthetic match results from KNOWN ground-truth parameters by
    sampling directly from the Dixon-Coles adjusted score distribution.

    Note on what this does and doesn't prove: this simulator imports _tau
    from the module under test, so test_mle_recovers_known_ground_truth_
    parameters below only checks that fitting recovers whatever _tau's
    generating process implies -- it is internally self-consistent, not an
    external check against the paper's formula. That's exactly why the
    lam/mu swap bug was invisible to this test (both simulation and fitting
    used the same swapped tau, so recovery "worked" regardless). External
    correctness against the reference formula is covered by
    test_tau_matches_hand_computed_values_on_special_cells and
    test_tau_regression_lambda_mu_not_swapped above instead."""
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
