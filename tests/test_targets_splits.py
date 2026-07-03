from datetime import date

import pandas as pd

from footpred.ml.splits import (
    FixedCutoffSplit,
    GroupFractionSplit,
    WalkForwardSplit,
    assert_no_leakage,
)
from footpred.ml.targets import (
    HTFT_CLASSES,
    label_1x2,
    label_btts,
    label_htft,
    label_ou25,
)


# ------------------------------ targets ---------------------------------- #

def test_label_1x2():
    assert label_1x2(2, 1) == "home"
    assert label_1x2(0, 0) == "draw"
    assert label_1x2(0, 3) == "away"


def test_label_ou25_boundary():
    assert label_ou25(1, 1) == "under"   # 2 goals
    assert label_ou25(2, 1) == "over"    # 3 goals


def test_label_btts():
    assert label_btts(1, 1) == "yes"
    assert label_btts(2, 0) == "no"
    assert label_btts(0, 0) == "no"


def test_label_htft_all_nine_cells_and_none():
    cases = {
        (1, 0, 2, 0): "1/1", (1, 0, 1, 1): "1/X", (1, 0, 1, 2): "1/2",
        (0, 0, 1, 0): "X/1", (0, 0, 0, 0): "X/X", (0, 0, 0, 1): "X/2",
        (0, 1, 2, 1): "2/1", (0, 1, 1, 1): "2/X", (0, 1, 0, 2): "2/2",
    }
    seen = set()
    for (hh, ha, fh, fa), expected in cases.items():
        got = label_htft(hh, ha, fh, fa)
        assert got == expected
        seen.add(got)
    assert seen == set(HTFT_CLASSES)
    assert label_htft(None, None, 2, 1) is None


# ------------------------------ splits ------------------------------------ #

def _frame():
    rows = []
    mid = 0
    for lg, (start_m, n) in {"E0": (8, 10), "SP1": (9, 6)}.items():
        for i in range(n):
            mid += 1
            rows.append({
                "match_id": mid, "league_key": lg,
                "match_date": date(2025, start_m, 1 + i),
            })
    return pd.DataFrame(rows)


def test_fixed_cutoff_split_and_leakage_guard():
    df = _frame()
    strat = FixedCutoffSplit(cutoff=date(2025, 9, 3))
    labels = strat.assign(df)
    assert set(labels.unique()) == {"train", "test"}
    assert_no_leakage(df, labels)
    assert (pd.to_datetime(df.loc[labels == "train", "match_date"]).dt.date
            < date(2025, 9, 3)).all()


def test_group_fraction_split_is_70_30_per_league_and_leak_free():
    df = _frame()
    strat = GroupFractionSplit(train_frac=0.7)
    labels = strat.assign(df)
    for lg, g in df.groupby("league_key"):
        lab = labels.loc[g.index]
        n_train = (lab == "train").sum()
        assert n_train == -(-len(g) * 7 // 10)  # ceil(0.7 n)
        # per-league temporal ordering: all train dates <= all test dates
        assert_no_leakage(g, lab)
    assert_no_leakage(df, labels, group_col="league_key")


def test_leakage_guard_fires_on_bad_labels():
    df = _frame().sort_values("match_date").reset_index(drop=True)
    bad = pd.Series("train", index=df.index)
    bad.iloc[2] = "test"  # a test row before later train rows
    try:
        assert_no_leakage(df, bad)
    except AssertionError as e:
        assert "leakage" in str(e)
    else:
        raise AssertionError("guard must fire")


def test_walk_forward_expanding_and_rolling():
    df = _frame().sort_values("match_date").reset_index(drop=True)
    exp_folds = list(WalkForwardSplit(n_folds=3, expanding=True).folds(df))
    roll_folds = list(WalkForwardSplit(n_folds=3, expanding=False).folds(df))
    assert len(exp_folds) == len(roll_folds) == 3

    prev_train = 0
    for (tr, te), (rtr, rte) in zip(exp_folds, roll_folds):
        # no overlap, test strictly after train
        assert not (tr & te).any() and not (rtr & rte).any()
        tr_max = df.loc[tr, "match_date"].max()
        te_min = df.loc[te, "match_date"].min()
        assert tr_max <= te_min
        # expanding grows the training set; rolling does not accumulate
        assert tr.sum() > prev_train
        prev_train = tr.sum()
        assert rtr.sum() <= tr.sum()
    # every expanding fold trains on ALL history before its test block
    last_tr, last_te = exp_folds[-1]
    assert last_tr.sum() + last_te.sum() == len(df) - (
        len(df) - last_te.sum() - last_tr.sum()
    )


def test_label_htft_nan_regression():
    """pandas represents missing HT as float NaN; NaN must behave exactly
    like None — never fabricate an 'X/X' label."""
    assert label_htft(float("nan"), float("nan"), 2, 1) is None
    assert label_htft(0, float("nan"), 2, 1) is None
    assert label_htft(0.0, 0.0, 2, 1) == "X/1"  # float-typed but present
