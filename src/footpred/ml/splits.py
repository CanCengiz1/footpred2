"""Temporal split strategies. Random splits are banned in this codebase:
they leak future team strength into training and fabricate backtest results.

Two stable interfaces (point 6 of the Sprint-2 review):

- SingleSplitStrategy.assign(df) -> pd.Series of {"train","test"} labels,
  used by DatasetBuilder. Implementations: FixedCutoffSplit,
  GroupFractionSplit (the 70/30-per-league Sprint 2 default).
- FoldSplitStrategy.folds(df) -> iterator of (train_mask, test_mask),
  used for walk-forward evaluation. WalkForwardSplit supports both rolling
  and expanding windows via ``expanding=``.

``assert_no_leakage`` is the guard every dataset build runs through.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Iterator, Optional, Protocol, Tuple

import pandas as pd

TRAIN, TEST = "train", "test"


class SingleSplitStrategy(Protocol):
    name: str

    def assign(self, df: pd.DataFrame) -> pd.Series: ...

    def describe(self) -> dict: ...


class FoldSplitStrategy(Protocol):
    name: str

    def folds(self, df: pd.DataFrame) -> Iterator[Tuple[pd.Series, pd.Series]]: ...


@dataclass
class FixedCutoffSplit:
    """Everything strictly before ``cutoff`` trains; the rest tests."""
    cutoff: date
    date_col: str = "match_date"
    name: str = "fixed_cutoff"

    def assign(self, df: pd.DataFrame) -> pd.Series:
        dates = pd.to_datetime(df[self.date_col]).dt.date
        return pd.Series(
            [TRAIN if d < self.cutoff else TEST for d in dates],
            index=df.index, name="split",
        )

    def describe(self) -> dict:
        return {"strategy": self.name, "cutoff": self.cutoff.isoformat(),
                "date_col": self.date_col}


@dataclass
class GroupFractionSplit:
    """Within each group (league), the earliest ``train_frac`` of rows by
    date train; the rest test. Sprint 2 default: 70/30 per league, so every
    league contributes to both eras despite different season calendars."""
    train_frac: float = 0.7
    group_col: str = "league_key"
    date_col: str = "match_date"
    name: str = "group_fraction"

    def assign(self, df: pd.DataFrame) -> pd.Series:
        if not 0.0 < self.train_frac < 1.0:
            raise ValueError("train_frac must be in (0, 1)")
        labels = pd.Series(TEST, index=df.index, name="split")
        for _, g in df.groupby(self.group_col):
            ordered = g.sort_values(
                [self.date_col, "match_id"] if "match_id" in g.columns else self.date_col
            )
            n_train = math.ceil(len(ordered) * self.train_frac)
            labels.loc[ordered.index[:n_train]] = TRAIN
        return labels

    def describe(self) -> dict:
        return {"strategy": self.name, "train_frac": self.train_frac,
                "group_col": self.group_col, "date_col": self.date_col}


@dataclass
class WalkForwardSplit:
    """Rolling-origin evaluation. Rows are ordered by date and cut into
    ``n_folds + 1`` contiguous blocks; fold i tests on block i+1 and trains
    on the immediately preceding block (rolling) or on ALL preceding blocks
    (expanding)."""
    n_folds: int = 4
    expanding: bool = True
    date_col: str = "match_date"
    name: str = "walk_forward"

    def folds(self, df: pd.DataFrame) -> Iterator[Tuple[pd.Series, pd.Series]]:
        if self.n_folds < 1:
            raise ValueError("n_folds must be >= 1")
        order = df.sort_values(self.date_col).index
        blocks = _contiguous_blocks(order, self.n_folds + 1)
        for i in range(1, len(blocks)):
            train_idx = (
                [ix for b in blocks[:i] for ix in b] if self.expanding else list(blocks[i - 1])
            )
            test_idx = list(blocks[i])
            yield (
                pd.Series(df.index.isin(train_idx), index=df.index),
                pd.Series(df.index.isin(test_idx), index=df.index),
            )


def _contiguous_blocks(index, k: int):
    n = len(index)
    size = math.ceil(n / k)
    return [index[i: i + size] for i in range(0, n, size)]


def assert_no_leakage(
    df: pd.DataFrame,
    labels: pd.Series,
    date_col: str = "match_date",
    group_col: Optional[str] = None,
) -> None:
    """max(train date) must precede or equal min(test date) — globally, or
    within each group for per-group strategies. Raises on violation."""
    def check(frame: pd.DataFrame, lab: pd.Series, scope: str) -> None:
        train_dates = pd.to_datetime(frame.loc[lab == TRAIN, date_col])
        test_dates = pd.to_datetime(frame.loc[lab == TEST, date_col])
        if train_dates.empty or test_dates.empty:
            return
        if train_dates.max() > test_dates.min():
            raise AssertionError(
                f"temporal leakage in {scope}: latest train date "
                f"{train_dates.max().date()} > earliest test date "
                f"{test_dates.min().date()}"
            )

    if group_col is None:
        check(df, labels, "global split")
    else:
        for key, g in df.groupby(group_col):
            check(g, labels.loc[g.index], f"group {key!r}")
