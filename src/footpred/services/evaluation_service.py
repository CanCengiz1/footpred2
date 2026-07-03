"""Application service for Sprint 2 evaluation workflows. The UI calls only
this; it orchestrates DatasetBuilder, MarketBaseline and BacktestRunner.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from footpred.infra.read_models import MatchOddsReader
from footpred.ml.backtest.runner import MARKETS, BacktestReport, BacktestRunner
from footpred.ml.baselines import MarketBaseline
from footpred.ml.datasets import DatasetBuilder, save_dataset
from footpred.ml.splits import GroupFractionSplit

DEFAULT_FEATURE_GROUPS = ["odds_core"]
DEFAULT_DEVIG_METHODS = ["proportional", "power", "shin"]


class EvaluationService:
    def __init__(self, reader: MatchOddsReader,
                 out_dir: str | Path = "data/datasets"):
        self._reader = reader
        self._out_dir = Path(out_dir)

    def build_dataset(
        self, train_frac: float = 0.7, persist: bool = True
    ) -> Tuple[pd.DataFrame, Dict, Optional[Path]]:
        builder = DatasetBuilder(
            reader=self._reader,
            feature_groups=DEFAULT_FEATURE_GROUPS,
            split=GroupFractionSplit(train_frac=train_frac),
        )
        frame, manifest = builder.build()
        path = save_dataset(frame, manifest, self._out_dir) if persist else None
        return frame, manifest, path

    def run_baseline_backtests(
        self, frame: pd.DataFrame, market: str,
        devig_methods: Optional[List[str]] = None,
        value_threshold: float = 0.02,
    ) -> List[BacktestReport]:
        """One report per de-vig method — the empirical arbitration table."""
        if market not in MARKETS:
            raise KeyError(f"unknown market {market!r}")
        runner = BacktestRunner(value_threshold=value_threshold)
        return [runner.run(frame, MarketBaseline(devig_method=m), market)
                for m in (devig_methods or DEFAULT_DEVIG_METHODS)]

    @staticmethod
    def comparison_table(reports: List[BacktestReport]) -> pd.DataFrame:
        return pd.DataFrame([r.summary() for r in reports])
