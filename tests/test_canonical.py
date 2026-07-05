import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from footpred.ml.backtest import runner as backtest_runner
from footpred.ml.backtest.runner import BacktestRunner
from footpred.ml.baselines import MarketBaseline
from footpred.ml.evidence import Finding
from footpred.ml.models.canonical import CanonicalPredictor
from footpred.ml.models.tabular import LEAGUE_COL, _odds_core_columns


class _FakePredictor:
    """A Predictor-protocol stand-in with a fixed prediction table, so the
    blending math can be tested in isolation without going through a real
    TabularPredictor fit."""

    def __init__(self, name: str, table: pd.DataFrame):
        self.name = name
        self._table = table

    def predict_proba(self, market: str, X: pd.DataFrame) -> pd.DataFrame:
        return self._table.loc[X.index]


def _finding(finding_id="f1", tier="provisionally_promoted", market="1x2", extra=("x",)):
    return Finding(finding_id=finding_id, tier=tier, market=market,
                   extra_columns=list(extra), description="d", retrospective_anchor="a")


# --------------------------- degenerate case ---------------------------- #

def test_degenerate_case_zero_findings_equals_baseline_exactly():
    X = pd.DataFrame({"dummy": [0, 1, 2]})
    baseline_table = pd.DataFrame({
        "home": [0.5, 0.4, 0.3], "draw": [0.3, 0.3, 0.3], "away": [0.2, 0.3, 0.4],
    }, index=X.index)
    baseline = _FakePredictor("B0", baseline_table)

    engine = CanonicalPredictor(baseline=baseline, findings=[], estimator_factory=lambda: None)
    engine.fit(X)
    canonical = engine.predict_proba("1x2", X)

    pd.testing.assert_frame_equal(canonical, baseline_table, check_exact=False, atol=1e-9)


# --------------------------- hand-computed blend ------------------------- #

def test_hand_computed_blend_at_fixed_weight():
    X = pd.DataFrame({"dummy": [0]})
    baseline_table = pd.DataFrame({"home": [0.5], "draw": [0.3], "away": [0.2]}, index=X.index)
    with_finding_table = pd.DataFrame({"home": [0.6], "draw": [0.25], "away": [0.15]}, index=X.index)

    baseline = _FakePredictor("B0", baseline_table)
    finding = _finding(tier="provisionally_promoted")

    engine = CanonicalPredictor(baseline=baseline, findings=[finding], estimator_factory=lambda: None)
    engine._finding_models = {"f1": _FakePredictor("f1", with_finding_table)}  # bypass fit()

    canonical = engine.predict_proba("1x2", X)

    base_logit = np.log(baseline_table.to_numpy())
    delta = np.log(with_finding_table.to_numpy()) - base_logit
    expected_logit = base_logit + 0.25 * delta
    expected = np.exp(expected_logit) / np.exp(expected_logit).sum(axis=1, keepdims=True)

    np.testing.assert_allclose(canonical.to_numpy(), expected, atol=1e-9)


def test_promoted_weight_is_full_strength():
    X = pd.DataFrame({"dummy": [0]})
    baseline_table = pd.DataFrame({"home": [0.5], "draw": [0.3], "away": [0.2]}, index=X.index)
    with_finding_table = pd.DataFrame({"home": [0.6], "draw": [0.25], "away": [0.15]}, index=X.index)
    baseline = _FakePredictor("B0", baseline_table)
    finding = _finding(tier="promoted")

    engine = CanonicalPredictor(baseline=baseline, findings=[finding], estimator_factory=lambda: None)
    engine._finding_models = {"f1": _FakePredictor("f1", with_finding_table)}
    canonical = engine.predict_proba("1x2", X)

    base_logit = np.log(baseline_table.to_numpy())
    delta = np.log(with_finding_table.to_numpy()) - base_logit
    expected_logit = base_logit + 1.0 * delta
    expected = np.exp(expected_logit) / np.exp(expected_logit).sum(axis=1, keepdims=True)
    np.testing.assert_allclose(canonical.to_numpy(), expected, atol=1e-9)


# --------------------------- zero-weight isolation ------------------------ #

def test_fit_never_builds_a_model_for_rejected_or_not_confirmed_findings():
    X = pd.DataFrame({"x": [0.1, 0.2, 0.3], "target_1x2": ["home", "draw", "away"],
                       LEAGUE_COL: ["E0", "E0", "E0"]})
    baseline = _FakePredictor("B0", pd.DataFrame(
        {"home": [0.5] * 3, "draw": [0.3] * 3, "away": [0.2] * 3}, index=X.index))
    findings = [_finding("rejected1", tier="rejected"),
                _finding("nc1", tier="not_confirmed")]

    engine = CanonicalPredictor(baseline=baseline, findings=findings, estimator_factory=lambda: None)
    engine.fit(X)
    assert engine._finding_models == {}


def test_rejected_finding_contributes_zero_even_if_a_model_exists_for_it():
    """Adversarial: force a model into _finding_models for a rejected
    finding (as if a bug bypassed fit()'s own filtering) and confirm the
    tier-based live_findings filter in _contributions still excludes it."""
    X = pd.DataFrame({"dummy": [0]})
    baseline_table = pd.DataFrame({"home": [0.5], "draw": [0.3], "away": [0.2]}, index=X.index)
    wild_table = pd.DataFrame({"home": [0.99], "draw": [0.005], "away": [0.005]}, index=X.index)
    baseline = _FakePredictor("B0", baseline_table)
    finding = _finding("rejected1", tier="rejected")

    engine = CanonicalPredictor(baseline=baseline, findings=[finding], estimator_factory=lambda: None)
    engine._finding_models = {"rejected1": _FakePredictor("rejected1", wild_table)}
    canonical = engine.predict_proba("1x2", X)

    pd.testing.assert_frame_equal(canonical, baseline_table, check_exact=False, atol=1e-9)


# --------------------------- counterfactual isolation --------------------- #

def test_counterfactual_isolates_promoted_only():
    X = pd.DataFrame({"dummy": [0]})
    baseline_table = pd.DataFrame({"home": [0.5], "draw": [0.3], "away": [0.2]}, index=X.index)
    provisional_table = pd.DataFrame({"home": [0.6], "draw": [0.25], "away": [0.15]}, index=X.index)
    promoted_table = pd.DataFrame({"home": [0.4], "draw": [0.35], "away": [0.25]}, index=X.index)

    baseline = _FakePredictor("B0", baseline_table)
    findings = [
        _finding("provisional1", tier="provisionally_promoted", extra=("x",)),
        _finding("promoted1", tier="promoted", extra=("y",)),
    ]
    engine = CanonicalPredictor(baseline=baseline, findings=findings, estimator_factory=lambda: None)
    engine._finding_models = {
        "provisional1": _FakePredictor("provisional1", provisional_table),
        "promoted1": _FakePredictor("promoted1", promoted_table),
    }
    explained = engine.explain("1x2", X)

    base_logit = np.log(baseline_table.to_numpy())
    promoted_delta = np.log(promoted_table.to_numpy()) - base_logit
    expected_cf_logit = base_logit + 1.0 * promoted_delta
    expected_cf = np.exp(expected_cf_logit) / np.exp(expected_cf_logit).sum(axis=1, keepdims=True)

    np.testing.assert_allclose(explained["counterfactual"].to_numpy(), expected_cf, atol=1e-9)
    assert not np.allclose(explained["canonical"].to_numpy(), explained["counterfactual"].to_numpy())


def test_counterfactual_equals_baseline_when_nothing_is_promoted_yet():
    """Today's actual state (see docs/VISION.md): zero promoted findings ->
    the counterfactual degenerates exactly to the baseline."""
    X = pd.DataFrame({"dummy": [0]})
    baseline_table = pd.DataFrame({"home": [0.5], "draw": [0.3], "away": [0.2]}, index=X.index)
    provisional_table = pd.DataFrame({"home": [0.6], "draw": [0.25], "away": [0.15]}, index=X.index)
    baseline = _FakePredictor("B0", baseline_table)
    finding = _finding(tier="provisionally_promoted")

    engine = CanonicalPredictor(baseline=baseline, findings=[finding], estimator_factory=lambda: None)
    engine._finding_models = {"f1": _FakePredictor("f1", provisional_table)}
    explained = engine.explain("1x2", X)

    pd.testing.assert_frame_equal(explained["counterfactual"], baseline_table,
                                   check_exact=False, atol=1e-9)


# --------------------------- validity ------------------------------------ #

def test_canonical_probabilities_valid_for_extreme_inputs():
    X = pd.DataFrame({"dummy": [0, 1]})
    baseline_table = pd.DataFrame(
        {"home": [0.98, 0.01], "draw": [0.01, 0.01], "away": [0.01, 0.98]}, index=X.index)
    extreme_table = pd.DataFrame(
        {"home": [0.001, 0.999], "draw": [0.001, 0.0005], "away": [0.998, 0.0005]}, index=X.index)
    baseline = _FakePredictor("B0", baseline_table)
    finding = _finding(tier="promoted")

    engine = CanonicalPredictor(baseline=baseline, findings=[finding], estimator_factory=lambda: None)
    engine._finding_models = {"f1": _FakePredictor("f1", extreme_table)}
    canonical = engine.predict_proba("1x2", X)

    assert (canonical.to_numpy() >= 0).all()
    assert (canonical.to_numpy() <= 1).all()
    np.testing.assert_allclose(canonical.sum(axis=1).to_numpy(), 1.0, atol=1e-9)


# --------------------------- abstention ----------------------------------- #

def test_baseline_abstention_propagates_to_canonical():
    X = pd.DataFrame({"dummy": [0, 1]})
    baseline_table = pd.DataFrame(
        {"home": [np.nan, 0.4], "draw": [np.nan, 0.3], "away": [np.nan, 0.3]}, index=X.index)
    baseline = _FakePredictor("B0", baseline_table)

    engine = CanonicalPredictor(baseline=baseline, findings=[], estimator_factory=lambda: None)
    canonical = engine.predict_proba("1x2", X)

    assert canonical.loc[0].isna().all()
    assert canonical.loc[1].notna().all()


def test_finding_abstention_falls_back_to_baseline_alone_for_that_row():
    X = pd.DataFrame({"dummy": [0, 1]})
    baseline_table = pd.DataFrame(
        {"home": [0.5, 0.5], "draw": [0.3, 0.3], "away": [0.2, 0.2]}, index=X.index)
    finding_table = pd.DataFrame(
        {"home": [np.nan, 0.7], "draw": [np.nan, 0.2], "away": [np.nan, 0.1]}, index=X.index)
    baseline = _FakePredictor("B0", baseline_table)
    finding = _finding(tier="promoted")

    engine = CanonicalPredictor(baseline=baseline, findings=[finding], estimator_factory=lambda: None)
    engine._finding_models = {"f1": _FakePredictor("f1", finding_table)}
    canonical = engine.predict_proba("1x2", X)

    pd.testing.assert_series_equal(canonical.loc[0], baseline_table.loc[0],
                                    check_exact=False, atol=1e-9, check_names=False)
    assert not np.allclose(canonical.loc[1].to_numpy(), baseline_table.loc[1].to_numpy())


# --------------------------- market-agnosticism --------------------------- #

def test_market_agnostic_with_arbitrary_selection_cardinality(monkeypatch):
    monkeypatch.setitem(backtest_runner.MARKETS, "fake_market", {
        "selections": ["s1", "s2", "s3", "s4"], "target": "target_fake",
    })
    X = pd.DataFrame({"dummy": [0]})
    baseline_table = pd.DataFrame({"s1": [0.4], "s2": [0.3], "s3": [0.2], "s4": [0.1]}, index=X.index)
    baseline = _FakePredictor("B0", baseline_table)

    engine = CanonicalPredictor(baseline=baseline, findings=[], estimator_factory=lambda: None)
    canonical = engine.predict_proba("fake_market", X)

    assert list(canonical.columns) == ["s1", "s2", "s3", "s4"]
    np.testing.assert_allclose(canonical.sum(axis=1).to_numpy(), 1.0, atol=1e-9)


def test_market_agnostic_binary_market_blend(monkeypatch):
    """A 2-outcome market (like btts) must blend identically to the 3-outcome
    case -- same code path, no hardcoded 3-way assumption anywhere."""
    monkeypatch.setitem(backtest_runner.MARKETS, "fake_binary", {
        "selections": ["yes", "no"], "target": "target_fake_binary",
    })
    X = pd.DataFrame({"dummy": [0]})
    baseline_table = pd.DataFrame({"yes": [0.6], "no": [0.4]}, index=X.index)
    with_finding_table = pd.DataFrame({"yes": [0.7], "no": [0.3]}, index=X.index)
    baseline = _FakePredictor("B0", baseline_table)
    finding = _finding(market="fake_binary")

    engine = CanonicalPredictor(baseline=baseline, findings=[finding], estimator_factory=lambda: None)
    engine._finding_models = {"f1": _FakePredictor("f1", with_finding_table)}
    canonical = engine.predict_proba("fake_binary", X)

    base_logit = np.log(baseline_table.to_numpy())
    delta = np.log(with_finding_table.to_numpy()) - base_logit
    expected_logit = base_logit + 0.25 * delta
    expected = np.exp(expected_logit) / np.exp(expected_logit).sum(axis=1, keepdims=True)
    np.testing.assert_allclose(canonical.to_numpy(), expected, atol=1e-9)


# --------------------------- end-to-end wiring ----------------------------- #

def _synthetic_end_to_end_frame(n=200, seed=7):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        signal = rng.normal(0, 1)
        outcome = "home" if signal > 0.3 else ("away" if signal < -0.3 else "draw")
        row = {
            "match_id": i, LEAGUE_COL: "E0", "target_1x2": outcome,
            "split": "train" if i < 150 else "test",
        }
        for c in _odds_core_columns():
            row[c] = rng.uniform(0.05, 0.95)
        # keep the exact 1x2 shin columns B0 and the finding both read valid
        # (summing to 1) so B0's own bad-sum renormalization isn't exercised.
        row["devig_1x2_home_bet365_shin"] = 0.4
        row["devig_1x2_draw_bet365_shin"] = 0.3
        row["devig_1x2_away_bet365_shin"] = 0.3
        row["devig_1x2_home_market_avg_shin"] = 0.4
        row["devig_1x2_draw_market_avg_shin"] = 0.3
        row["devig_1x2_away_market_avg_shin"] = 0.3
        row["engineered_signal"] = signal
        rows.append(row)
    return pd.DataFrame(rows)


def test_end_to_end_through_unmodified_backtest_runner():
    frame = _synthetic_end_to_end_frame()
    train = frame[frame["split"] == "train"]

    finding = _finding(finding_id="f1", tier="provisionally_promoted", extra=("engineered_signal",))
    baseline = MarketBaseline()
    engine = CanonicalPredictor(
        baseline=baseline, findings=[finding],
        estimator_factory=lambda: LogisticRegression(max_iter=1000),
    )
    engine.fit(train)

    report = BacktestRunner().run(frame, engine, "1x2")
    assert report.n_rows_scored > 0
    assert report.model == "FootPred"
