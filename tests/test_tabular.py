import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from footpred.domain.entities import League, Match, MatchStatus, Team
from footpred.infra.memory import InMemoryUnitOfWork
from footpred.infra.read_models import InMemoryMatchOddsReader
from footpred.ml.backtest.runner import BacktestRunner
from footpred.ml.datasets import DatasetBuilder
from footpred.ml.models.tabular import (
    LEAGUE_COL, TabularPredictor, _odds_consensus_columns,
    _odds_core_columns, _odds_divergence_columns, _team_form_columns,
    resolve_feature_columns,
)
from footpred.ml.splits import GroupFractionSplit


# --------------------------- feature-column allowlist ----------------------- #

def _toy_frame():
    """A frame mixing identity/target columns with real feature columns --
    the exact adversarial shape resolve_feature_columns must handle safely."""
    n = 6
    data = {
        "match_id": range(n), "ft_home": [1] * n, "ft_away": [0] * n,
        "target_1x2": ["home"] * n, "target_ou_2_5": ["over"] * n,
        LEAGUE_COL: ["E0"] * n,
    }
    for c in _team_form_columns():
        data[c] = np.random.rand(n)
    for c in _odds_core_columns():
        data[c] = np.random.rand(n)
    return pd.DataFrame(data)


def test_resolve_feature_columns_is_allowlist_not_blocklist():
    frame = _toy_frame()
    resolved = resolve_feature_columns(frame, ["odds_core", "team_form"])
    resolved_set = set(resolved)
    # every resolved column really is a known feature column
    assert resolved_set <= set(_team_form_columns()) | set(_odds_core_columns())
    # identity/target columns must never appear, even though they sit in the
    # exact same frame right alongside the real feature columns
    for leak in ["match_id", "ft_home", "ft_away", "target_1x2", "target_ou_2_5", LEAGUE_COL]:
        assert leak not in resolved_set


def test_resolve_feature_columns_unknown_group_raises():
    with pytest.raises(KeyError, match="unsupported feature group"):
        resolve_feature_columns(_toy_frame(), ["not_a_real_group"])


def test_resolve_feature_columns_empty_result_raises():
    frame = pd.DataFrame({"match_id": [1, 2]})  # no feature columns at all
    with pytest.raises(ValueError, match="resolved to zero columns"):
        resolve_feature_columns(frame, ["team_form"])


def test_odds_consensus_and_divergence_partition_odds_core():
    consensus, divergence, full = (set(_odds_consensus_columns()),
                                    set(_odds_divergence_columns()),
                                    set(_odds_core_columns()))
    assert consensus & divergence == set()  # no overlap
    assert consensus | divergence == full   # covers odds_core exactly
    assert divergence == {
        "div_1x2_home_shin", "div_1x2_draw_shin", "div_1x2_away_shin",
        "div_ou_2_5_over_shin", "div_ou_2_5_under_shin",
    }


# --------------------------- fit/predict behavior ---------------------------- #

def _synthetic_dataset(n=200, leagues=("E0", "E1"), seed=0, all_nan_ou_odds=False):
    """Minimal synthetic frame with real feature-column names, a signal
    feature that determines the outcome, and the identity/target columns a
    real dataset frame would also carry."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        lg = leagues[i % len(leagues)]
        signal = rng.normal(0, 1)
        outcome = "home" if signal > 0.3 else ("away" if signal < -0.3 else "draw")
        row = {
            "match_id": i, "ft_home": 1, "ft_away": 0, LEAGUE_COL: lg,
            "target_1x2": outcome, "target_ou_2_5": "over" if signal > 0 else "under",
        }
        for c in _team_form_columns():
            row[c] = signal + rng.normal(0, 0.1) if c == "home_form_pts_last5" else rng.normal(0, 1)
        for c in _odds_core_columns():
            row[c] = np.nan if (all_nan_ou_odds and "ou_2_5" in c) else rng.uniform(0, 1)
        rows.append(row)
    return pd.DataFrame(rows)


def test_preprocessor_uses_train_only_statistics():
    train = _synthetic_dataset(n=100, seed=1)
    col = "home_form_pts_last5"
    train_median = train[col].median()

    predictor = TabularPredictor(["team_form", "odds_core"],
                                  lambda: LogisticRegression(max_iter=1000))
    predictor.fit(train)

    # the imputer's learned statistic for this column is exactly the TRAIN
    # median -- frozen at fit time
    col_idx = predictor._feature_cols.index(col)
    learned_median = (predictor._preprocessor.named_transformers_["numeric"]
                      .named_steps["impute"].statistics_[col_idx])
    assert math.isclose(learned_median, train_median, rel_tol=1e-9)

    # a test-time row with NaN in that column must be imputed using that
    # frozen train statistic, not something recomputed from test data --
    # confirmed by checking it transforms identically to manually
    # substituting the train median by hand
    test_row_nan = train.iloc[[0]].copy()
    test_row_nan[col] = np.nan
    test_row_manual = train.iloc[[0]].copy()
    test_row_manual[col] = train_median

    Xt_nan = predictor._preprocessor.transform(test_row_nan)
    Xt_manual = predictor._preprocessor.transform(test_row_manual)
    np.testing.assert_allclose(Xt_nan, Xt_manual, atol=1e-9)


def test_unseen_league_abstains():
    train = _synthetic_dataset(n=100, leagues=("E0", "E1"), seed=2)
    predictor = TabularPredictor(["team_form", "odds_core"],
                                  lambda: LogisticRegression(max_iter=1000)).fit(train)

    test = _synthetic_dataset(n=4, leagues=("SP1",), seed=3)
    probs = predictor.predict_proba("1x2", test)
    assert probs.isna().all(axis=None)


def test_unseen_team_does_not_abstain():
    """Team identity isn't a raw feature here -- only aggregated team_form
    stats are, and a first-ever-match team just gets NaN there (imputed),
    same as any other missing value. This is the concrete advantage over
    DixonColesPredictor, which must abstain on any unseen team."""
    train = _synthetic_dataset(n=100, seed=4)
    predictor = TabularPredictor(["team_form", "odds_core"],
                                  lambda: LogisticRegression(max_iter=1000)).fit(train)

    test = train.iloc[[0]].copy()
    for c in _team_form_columns():
        test[c] = np.nan  # "brand new team" signature: no history yet
    probs = predictor.predict_proba("1x2", test)
    assert probs.notna().all(axis=None)
    assert math.isclose(probs.iloc[0].sum(), 1.0, abs_tol=1e-9)


def test_all_nan_feature_column_does_not_crash_imputation():
    """Mirrors the real coverage gap found this session: pre-2019
    football-data.co.uk files have zero O/U 2.5 odds at all, so within a
    training window restricted to that era, every devig_ou_2_5_* column is
    100% NaN. Must not crash."""
    train = _synthetic_dataset(n=60, seed=5, all_nan_ou_odds=True)
    predictor = TabularPredictor(["team_form", "odds_core"],
                                  lambda: LogisticRegression(max_iter=1000)).fit(train)
    probs = predictor.predict_proba("1x2", train.iloc[:5])
    assert probs.notna().all(axis=None)


class _ReversedOrderEstimator:
    """Fake estimator whose classes_ come back in a deliberately wrong
    order, to prove TabularPredictor reindexes rather than trusting order."""

    def fit(self, X, y):
        self.classes_ = np.array(sorted(set(y), reverse=True))  # deliberately not alphabetical
        self._n = len(self.classes_)
        return self

    def predict_proba(self, X):
        n = len(X)
        # arbitrary but valid distribution, same for every row
        p = np.linspace(1, self._n, self._n)
        p = p / p.sum()
        return np.tile(p, (n, 1))


def test_output_columns_match_market_order_regardless_of_estimator_class_order():
    train = _synthetic_dataset(n=60, seed=6)
    predictor = TabularPredictor(["team_form", "odds_core"], _ReversedOrderEstimator).fit(train)
    probs = predictor.predict_proba("1x2", train.iloc[:5])
    assert list(probs.columns) == ["home", "draw", "away"]
    assert np.allclose(probs.sum(axis=1), 1.0)


def test_probabilities_sum_to_one_for_both_markets():
    train = _synthetic_dataset(n=150, seed=7)
    predictor = TabularPredictor(["team_form", "odds_core"],
                                  lambda: LogisticRegression(max_iter=1000)).fit(train)
    for market in ["1x2", "ou_2.5"]:
        probs = predictor.predict_proba(market, train.iloc[:10])
        assert np.allclose(probs.sum(axis=1), 1.0)


def test_learns_obviously_learnable_pattern():
    """Smoke test for the whole pipeline (selection -> preprocessing -> fit
    -> predict), not a numerical-recovery test -- sklearn's own fit is
    already well-tested, so this just proves our glue code doesn't break an
    obviously-learnable signal."""
    train = _synthetic_dataset(n=400, seed=8)
    test = _synthetic_dataset(n=200, seed=9)
    predictor = TabularPredictor(["team_form", "odds_core"],
                                  lambda: LogisticRegression(max_iter=1000)).fit(train)
    probs = predictor.predict_proba("1x2", test)
    predicted = probs.idxmax(axis=1)
    accuracy = (predicted.to_numpy() == test["target_1x2"].to_numpy()).mean()
    assert accuracy > 0.6  # well above chance (1/3) and the majority-class rate


# --------------------------- end-to-end harness wiring ---------------------- #

def test_tabular_plugs_into_unmodified_backtest_runner():
    """Fits on a built dataset's train split and scores through
    BacktestRunner exactly as MarketBaseline/DixonColesPredictor do -- the
    actual point of the Predictor protocol design, same claim
    test_dixon_coles_plugs_into_unmodified_backtest_runner makes for DC."""
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
    for _ in range(15):
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

    predictor = TabularPredictor(
        feature_groups=["team_form"],  # this toy dataset has no odds quotes
        estimator_factory=lambda: LogisticRegression(max_iter=1000),
    ).fit(frame[frame["split"] == "train"])
    report = BacktestRunner(value_threshold=0.02).run(frame, predictor, "1x2")

    assert report.n_rows_scored > 0
    assert report.log_loss > 0
    assert 0 < report.brier < 2
    assert report.calibration["n_points"] == report.n_rows_scored * 3
