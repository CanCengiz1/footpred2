"""Backtest runner: (dataset, Predictor, market) -> BacktestReport.

The Predictor protocol is the stable interface every future model implements
(market baseline now; Dixon-Coles, gradient boosting, neural models later).
The runner never knows which model it is scoring — this file must not change
when models are added (Sprint-2 review point 5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Protocol

import numpy as np
import pandas as pd

from footpred.domain.entities import Bookmaker
from footpred.infra.read_models import odds_col
from footpred.ml.backtest.metrics import brier_score, calibration_table, log_loss
from footpred.ml.backtest.simulator import simulate

MARKETS: Dict[str, dict] = {
    "1x2": {"selections": ["home", "draw", "away"], "target": "target_1x2"},
    "ou_2.5": {"selections": ["over", "under"], "target": "target_ou_2_5"},
}


class Predictor(Protocol):
    """Stable model interface. predict_proba returns an (n, k) frame of
    probabilities, columns == market selections, aligned to X's index,
    rows summing to 1 (NaN rows allowed where the model abstains)."""
    name: str

    def predict_proba(self, market: str, X: pd.DataFrame) -> pd.DataFrame: ...


@dataclass
class BacktestReport:
    market: str
    model: str
    n_rows_available: int
    n_rows_scored: int
    log_loss: float
    brier: float
    calibration: Dict
    simulations: List[Dict] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def summary(self) -> Dict:
        return {
            "market": self.market, "model": self.model,
            "n_scored": self.n_rows_scored, "log_loss": round(self.log_loss, 5),
            "brier": round(self.brier, 5), "ece": self.calibration["ece"],
            **{f"sim_{s['mode']}": s["roi"] for s in self.simulations},
        }


class BacktestRunner:
    def __init__(self, value_threshold: float = 0.02):
        self._theta = value_threshold

    def run(self, df: pd.DataFrame, predictor: Predictor, market: str,
            split: str = "test") -> BacktestReport:
        if market not in MARKETS:
            raise KeyError(f"unknown market {market!r}; have {sorted(MARKETS)}")
        meta = MARKETS[market]
        sels: List[str] = meta["selections"]
        rows = df[df["split"] == split] if "split" in df.columns else df
        n_available = len(rows)

        probs = predictor.predict_proba(market, rows)
        if list(probs.columns) != sels:
            raise ValueError(f"{predictor.name}: expected columns {sels}, "
                             f"got {list(probs.columns)}")

        odds = _best_odds(rows, market, sels)
        outcomes = rows[meta["target"]]

        ok = probs.notna().all(axis=1) & outcomes.notna()
        probs, outcomes, odds = probs[ok], outcomes[ok], odds[ok]
        notes = []
        if int((~ok).sum()):
            notes.append(f"{int((~ok).sum())} rows skipped (model abstained "
                         "or target missing)")

        report = BacktestReport(
            market=market, model=predictor.name,
            n_rows_available=n_available, n_rows_scored=int(len(probs)),
            log_loss=log_loss(probs, outcomes),
            brier=brier_score(probs, outcomes),
            calibration=calibration_table(probs, outcomes),
            notes=notes,
        )
        for mode in ("value_threshold", "bet_all"):
            report.simulations.append(
                simulate(probs, odds, outcomes, mode=mode, threshold=self._theta))
        return report


def _best_odds(rows: pd.DataFrame, market: str, sels: List[str]) -> pd.DataFrame:
    """Bet365 prices with market-average fallback per cell (Bet365 primary
    per project constraints)."""
    out = pd.DataFrame(index=rows.index)
    for s in sels:
        primary = odds_col(market, s, Bookmaker.BET365.value)
        fallback = odds_col(market, s, Bookmaker.MARKET_AVG.value)
        p = rows[primary] if primary in rows.columns else pd.Series(np.nan, index=rows.index)
        f = rows[fallback] if fallback in rows.columns else pd.Series(np.nan, index=rows.index)
        out[s] = p.fillna(f)
    return out
