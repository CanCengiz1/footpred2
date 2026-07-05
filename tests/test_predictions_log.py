import json

import numpy as np
import pandas as pd

from footpred.ml.evidence import Finding
from footpred.ml.models.canonical import CanonicalPredictor
from footpred.ml.predictions_log import (
    build_predictions_frame, content_hash, load_predictions, save_predictions,
)


class _FakePredictor:
    def __init__(self, name, table):
        self.name = name
        self._table = table

    def predict_proba(self, market, X):
        return self._table.loc[X.index]


def _finding(finding_id="f1", tier="provisionally_promoted", market="1x2"):
    return Finding(finding_id=finding_id, tier=tier, market=market,
                   extra_columns=["x"], description="d", retrospective_anchor="a")


def _engine_with_one_finding():
    X = pd.DataFrame({"dummy": [10, 20]})
    baseline_table = pd.DataFrame({"home": [0.5, 0.4], "draw": [0.3, 0.3], "away": [0.2, 0.3]}, index=X.index)
    finding_table = pd.DataFrame({"home": [0.6, 0.35], "draw": [0.25, 0.35], "away": [0.15, 0.3]}, index=X.index)
    baseline = _FakePredictor("B0", baseline_table)
    finding = _finding()
    engine = CanonicalPredictor(baseline=baseline, findings=[finding], estimator_factory=lambda: None)
    engine._finding_models = {"f1": _FakePredictor("f1", finding_table)}
    return engine, X, finding


# --------------------------- frame shape / content ------------------------ #

def test_frame_has_one_row_per_match_role_selection_plus_contributions():
    engine, X, finding = _engine_with_one_finding()
    frame = build_predictions_frame(engine, "1x2", X)

    n_matches, n_sels = len(X), 3
    expected_value_rows = n_matches * n_sels * 3  # baseline, canonical, counterfactual
    expected_contribution_rows = n_matches * n_sels * 1  # one live finding
    assert len(frame) == expected_value_rows + expected_contribution_rows
    assert set(frame["kind"]) == {"value", "contribution"}
    assert set(frame.loc[frame["kind"] == "value", "role"]) == {"baseline", "canonical", "counterfactual"}


def test_value_rows_match_engine_explain_output():
    engine, X, finding = _engine_with_one_finding()
    frame = build_predictions_frame(engine, "1x2", X)
    explained = engine.explain("1x2", X)

    for role in ("baseline", "canonical", "counterfactual"):
        for match_id in X.index:
            for sel in ("home", "draw", "away"):
                row = frame[(frame["kind"] == "value") & (frame["role"] == role)
                            & (frame["match_id"] == match_id) & (frame["selection"] == sel)]
                assert len(row) == 1
                expected = explained[role].loc[match_id, sel]
                np.testing.assert_allclose(row["value"].iloc[0], expected, atol=1e-9)


def test_contribution_rows_carry_finding_metadata():
    engine, X, finding = _engine_with_one_finding()
    frame = build_predictions_frame(engine, "1x2", X)
    contrib = frame[frame["kind"] == "contribution"]
    assert (contrib["finding_id"] == "f1").all()
    assert (contrib["tier"] == "provisionally_promoted").all()
    assert (contrib["weight"] == 0.25).all()
    assert contrib["role"].isna().all()
    assert contrib["model_hash"].notna().all()
    assert contrib["model_hash"].nunique() == 1  # same fitted model -> same fingerprint


def test_value_rows_have_no_model_hash():
    engine, X, finding = _engine_with_one_finding()
    frame = build_predictions_frame(engine, "1x2", X)
    assert frame.loc[frame["kind"] == "value", "model_hash"].isna().all()


# --------------------------- content hash / determinism ------------------- #

def test_content_hash_deterministic_and_order_independent():
    engine, X, finding = _engine_with_one_finding()
    frame = build_predictions_frame(engine, "1x2", X)
    shuffled = frame.sample(frac=1.0, random_state=0).reset_index(drop=True)

    assert content_hash(frame) == content_hash(shuffled)


def test_content_hash_changes_when_a_value_changes():
    engine, X, finding = _engine_with_one_finding()
    frame = build_predictions_frame(engine, "1x2", X)
    mutated = frame.copy()
    mutated.loc[mutated.index[0], "value"] = (mutated.loc[mutated.index[0], "value"] or 0.0) + 0.1

    assert content_hash(frame) != content_hash(mutated)


# --------------------------- save / load / manifest ------------------------ #

def test_save_and_load_round_trips(tmp_path):
    engine, X, finding = _engine_with_one_finding()
    frame = build_predictions_frame(engine, "1x2", X)

    path = save_predictions(frame, [finding], tmp_path)
    loaded = load_predictions(path)

    assert len(loaded) == len(frame)
    assert set(loaded.columns) == set(frame.columns)


def test_manifest_captures_tier_weights_and_registry_snapshot(tmp_path):
    engine, X, finding = _engine_with_one_finding()
    frame = build_predictions_frame(engine, "1x2", X)

    path = save_predictions(frame, [finding], tmp_path)
    manifest_candidates = list(tmp_path.glob("predictions-*.manifest.json"))
    assert len(manifest_candidates) == 1
    manifest = json.loads(manifest_candidates[0].read_text(encoding="utf-8"))

    assert manifest["mode"] == "backtest"
    assert manifest["tier_weights"] == {
        "rejected": 0.0, "not_confirmed": 0.0,
        "provisionally_promoted": 0.25, "promoted": 1.0,
    }
    assert len(manifest["findings_registry_snapshot"]) == 1
    assert manifest["findings_registry_snapshot"][0]["finding_id"] == "f1"
    assert manifest["findings_registry_snapshot"][0]["tier"] == "provisionally_promoted"
    assert manifest["content_hash"] == content_hash(frame)
    assert manifest["rows"] == len(frame)
    assert "f1" in manifest["model_hashes"]
    expected_hash = frame.loc[frame["kind"] == "contribution", "model_hash"].iloc[0]
    assert manifest["model_hashes"]["f1"] == expected_hash
