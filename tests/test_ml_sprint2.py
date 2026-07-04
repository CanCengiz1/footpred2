import math
from pathlib import Path

import numpy as np
import pandas as pd

from footpred.infra.memory import InMemoryUnitOfWork
from footpred.infra.read_models import InMemoryMatchOddsReader, odds_col
from footpred.ingest.mapping import FOOTBALL_DATA_CO_UK
from footpred.ingest.pipeline import ImportPipeline
from footpred.ingest.readers import read_table
from footpred.ingest.resolution import normalize_name
from footpred.ml.backtest.metrics import brier_score, calibration_table, log_loss
from footpred.ml.backtest.runner import BacktestRunner
from footpred.ml.backtest.simulator import simulate
from footpred.ml.baselines import MarketBaseline
from footpred.ml.datasets import DatasetBuilder, content_hash, load_dataset, save_dataset
from footpred.ml.features.base import (
    FeatureContext,
    get_feature_group,
    register_feature_group,
)
from footpred.ml.splits import GroupFractionSplit
from footpred.services.evaluation_service import EvaluationService

SAMPLE = Path(__file__).parent / "data" / "sample_fd.csv"


def _seeded_uow() -> InMemoryUnitOfWork:
    uow = InMemoryUnitOfWork()
    df = read_table(SAMPLE, "sample_fd.csv")
    ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(df, "sample_fd.csv")
    return uow


# --------------------------- read model ----------------------------------- #

def test_read_model_pivots_odds_wide():
    uow = _seeded_uow()
    frame = InMemoryMatchOddsReader(uow).load_completed()
    assert len(frame) == 6
    assert odds_col("1x2", "home", "bet365") in frame.columns
    assert odds_col("ou_2.5", "over", "market_avg") in frame.columns
    arsenal = frame.iloc[0]
    assert arsenal[odds_col("1x2", "home", "bet365")] == 1.90
    assert bool(frame["has_ht"].iloc[0]) is True
    # HT nulled on two rows: partial HT (Newcastle) + impossible HT (Brentford)
    assert (~frame["has_ht"]).sum() == 2

    # team identity travels through the flat frame (needed by as-of features)
    arsenal_id = uow.teams.get_by_normalized(normalize_name("Arsenal")).id
    chelsea_id = uow.teams.get_by_normalized(normalize_name("Chelsea")).id
    assert {"home_team_id", "away_team_id"} <= set(frame.columns)
    assert arsenal["home_team_id"] == arsenal_id
    assert arsenal["away_team_id"] == chelsea_id


# --------------------------- features ------------------------------------- #

def test_odds_feature_group_columns_and_values():
    frame = InMemoryMatchOddsReader(_seeded_uow()).load_completed()
    feats = get_feature_group("odds_core").build(FeatureContext(matches=frame))

    row = feats.iloc[0]  # Arsenal-Chelsea 1.90/3.60/4.20
    assert math.isclose(row["imp_1x2_home_bet365_raw"], 1 / 1.90, rel_tol=1e-9)
    booksum = 1 / 1.90 + 1 / 3.60 + 1 / 4.20
    assert math.isclose(row["ovr_1x2_bet365"], booksum - 1.0, rel_tol=1e-9)
    for method in ("proportional", "power", "shin"):
        total = sum(row[f"devig_1x2_{s}_bet365_{method}"]
                    for s in ("home", "draw", "away"))
        assert math.isclose(total, 1.0, abs_tol=1e-9)
    # divergence exists and equals b365 - avg under shin
    d = row["div_1x2_home_shin"]
    assert math.isclose(
        d, row["devig_1x2_home_bet365_shin"] - row["devig_1x2_home_market_avg_shin"],
        abs_tol=1e-12)

    # Aston Villa row had B365>2.5 = 0.50 dropped at import -> incomplete
    # OU market for bet365 -> NaN features for that market/bookmaker
    incomplete = feats["imp_ou_2_5_over_bet365_raw"].isna().sum()
    assert incomplete >= 1


def test_feature_registry_extension_flows_into_dataset_without_builder_change():
    class DummyGroup:
        name = "dummy_ones"
        version = "0.1"

        def build(self, ctx):
            return pd.DataFrame({"dummy_one": 1.0},
                                index=ctx.matches["match_id"])

    try:
        register_feature_group(DummyGroup())
    except ValueError:
        pass  # already registered by a previous test run in same process

    uow = _seeded_uow()
    builder = DatasetBuilder(InMemoryMatchOddsReader(uow),
                             feature_groups=["odds_core", "dummy_ones"],
                             split=GroupFractionSplit(0.7))
    frame, manifest = builder.build()
    assert "dummy_one" in frame.columns
    names = {g["name"]: g["version"] for g in manifest["feature_groups"]}
    assert names["dummy_ones"] == "0.1" and names["odds_core"] == "1.0"


# --------------------------- metrics --------------------------------------- #

def test_log_loss_and_brier_hand_computed():
    probs = pd.DataFrame({"home": [0.5, 0.2], "draw": [0.3, 0.3],
                          "away": [0.2, 0.5]})
    outcomes = pd.Series(["home", "away"])
    expected_ll = -(math.log(0.5) + math.log(0.5)) / 2
    assert math.isclose(log_loss(probs, outcomes), expected_ll, rel_tol=1e-12)
    expected_brier = (((0.5 - 1) ** 2 + 0.3 ** 2 + 0.2 ** 2)
                      + (0.2 ** 2 + 0.3 ** 2 + (0.5 - 1) ** 2)) / 2
    assert math.isclose(brier_score(probs, outcomes), expected_brier, rel_tol=1e-12)


def test_calibration_perfect_and_ece():
    # constant 0.5 prediction, outcomes 50/50 -> ECE ~ 0
    probs = pd.DataFrame({"over": [0.5] * 4, "under": [0.5] * 4})
    outcomes = pd.Series(["over", "over", "under", "under"])
    cal = calibration_table(probs, outcomes, n_bins=10)
    assert cal["n_points"] == 8
    nonempty = [b for b in cal["bins"] if b["n"]]
    assert len(nonempty) == 1 and math.isclose(nonempty[0]["observed_freq"], 0.5)
    assert cal["ece"] < 1e-9


# --------------------------- simulator ------------------------------------- #

def test_simulator_handcrafted_pnl():
    probs = pd.DataFrame({"home": [0.60, 0.10], "away": [0.40, 0.90]})
    odds = pd.DataFrame({"home": [2.00, 5.00], "away": [2.00, 1.20]})
    outcomes = pd.Series(["home", "away"])
    # value bets (theta=2%): row0 home 0.6*2=1.2 yes (wins +1);
    # row1 away 0.9*1.2=1.08 yes (wins +0.2); row1 home 0.1*5=0.5 no;
    # row0 away 0.4*2=0.8 no
    res = simulate(probs, odds, outcomes, mode="value_threshold", threshold=0.02)
    assert res["n_bets"] == 2
    assert math.isclose(res["profit"], 1.0 + 0.2, abs_tol=1e-9)
    assert math.isclose(res["roi"], 1.2 / 2, abs_tol=1e-9)

    res_all = simulate(probs, odds, outcomes, mode="bet_all")
    # 4 bets: +1 (home@2 wins), -1, -1, +0.2 -> profit -0.8
    assert res_all["n_bets"] == 4
    assert math.isclose(res_all["profit"], -0.8, abs_tol=1e-9)


def test_simulator_never_bets_unquoted():
    probs = pd.DataFrame({"over": [0.9], "under": [0.1]})
    odds = pd.DataFrame({"over": [np.nan], "under": [np.nan]})
    res = simulate(probs, odds, pd.Series(["over"]), mode="bet_all")
    assert res["n_bets"] == 0 and res["roi"] is None


def test_market_baseline_vs_own_prices_yields_no_value_bets():
    """Deterministic harness proof: proportional de-vig probs times the same
    book's odds equal 1/booksum < 1 for every selection, so the value rule
    must produce ZERO bets when B0 is scored against its own prices."""
    uow = _seeded_uow()
    frame, _, _ = EvaluationService(
        InMemoryMatchOddsReader(uow)).build_dataset(persist=False)
    runner = BacktestRunner(value_threshold=0.02)
    report = runner.run(frame, MarketBaseline("proportional"), "1x2", split="test")
    value_sim = next(s for s in report.simulations if s["mode"] == "value_threshold")
    assert value_sim["n_bets"] == 0


# --------------------------- datasets -------------------------------------- #

def test_dataset_build_end_to_end_with_manifest(tmp_path):
    uow = _seeded_uow()
    service = EvaluationService(InMemoryMatchOddsReader(uow), out_dir=tmp_path)
    frame, manifest, path = service.build_dataset(train_frac=0.7)

    assert manifest["schema_version"] == "2.1"
    assert manifest["rows"]["total"] == 6
    assert manifest["rows"]["train"] + manifest["rows"]["test"] == 6
    assert set(frame["split"].unique()) <= {"train", "test"}
    assert {"target_1x2", "target_ou_2_5", "target_btts", "target_htft"} <= set(frame.columns)
    # team identity and raw goals travel into the artifact (needed by
    # per-team goal models -- target_1x2 alone loses the scoreline)
    assert {"home_team_id", "away_team_id", "ft_home", "ft_away"} <= set(frame.columns)
    assert frame["home_team_id"].notna().all() and frame["away_team_id"].notna().all()
    assert frame["ft_home"].notna().all() and frame["ft_away"].notna().all()
    # HT/FT target None exactly where HT missing (partial + impossible rows)
    assert frame["target_htft"].isna().sum() == 2
    assert (frame["target_htft"].isna() == ~frame["has_ht"]).all()
    # artifact round-trips
    assert path is not None and path.exists()
    reloaded = load_dataset(path)
    assert len(reloaded) == 6
    manifest_file = list(Path(tmp_path).glob("*.manifest.json"))
    assert len(manifest_file) == 1


def test_dataset_hash_is_deterministic():
    uow = _seeded_uow()
    b = lambda: DatasetBuilder(InMemoryMatchOddsReader(uow), ["odds_core"],
                               GroupFractionSplit(0.7)).build()
    f1, m1 = b()
    f2, m2 = b()
    assert m1["content_hash"] == m2["content_hash"] == content_hash(f2)


# --------------------------- runner + baseline e2e ------------------------- #

def test_baseline_backtest_reports_all_devig_methods():
    uow = _seeded_uow()
    service = EvaluationService(InMemoryMatchOddsReader(uow))
    frame, _, _ = service.build_dataset(persist=False)
    reports = service.run_baseline_backtests(frame, "1x2")
    assert len(reports) == 3
    for r in reports:
        assert r.n_rows_scored > 0
        assert r.log_loss > 0 and 0 < r.brier < 2
        assert r.calibration["n_points"] == r.n_rows_scored * 3
    table = service.comparison_table(reports)
    assert set(table["model"]) == {"B0-market[proportional]",
                                   "B0-market[power]", "B0-market[shin]"}
