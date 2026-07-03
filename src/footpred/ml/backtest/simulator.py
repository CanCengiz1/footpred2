"""Flat-stake betting simulation. Two modes:

- value_threshold: bet 1 unit on every selection where p * odds > 1 + theta.
  The economically meaningful mode.
- bet_all: bet 1 unit on every quoted selection. Diagnostic mode — under
  the market baseline evaluated against its own prices its ROI must come
  out ~= -overround/(1+overround); if the harness shows the market beating
  itself, the harness is broken. This is the calibration proof of the
  whole backtesting stack.

Staking is deliberately flat in Sprint 2. Kelly staking arrives with the
combo services (Sprint 7); mixing staking research into harness validation
would confound both.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd


def simulate(
    probs: pd.DataFrame,
    odds: pd.DataFrame,
    outcomes: pd.Series,
    mode: str = "value_threshold",
    threshold: float = 0.02,
    stake: float = 1.0,
) -> Dict:
    """probs/odds: (n, k) frames with identical selection columns; NaN odds
    == not quoted (never bet). Returns counts, profit, ROI, hit rate."""
    if list(probs.columns) != list(odds.columns):
        raise ValueError("probs and odds must share identical selection columns")
    p = probs.to_numpy(dtype=float)
    o = odds.to_numpy(dtype=float)
    quoted = ~np.isnan(o) & ~np.isnan(p)

    if mode == "value_threshold":
        placed = quoted & (p * o > 1.0 + threshold)
    elif mode == "bet_all":
        placed = quoted
    else:
        raise ValueError(f"unknown mode {mode!r}")

    cols = list(probs.columns)
    idx = outcomes.map({c: i for i, c in enumerate(cols)}).to_numpy()
    won = np.zeros_like(p, dtype=bool)
    won[np.arange(len(outcomes)), idx] = True

    n_bets = int(placed.sum())
    if n_bets == 0:
        return {"mode": mode, "threshold": threshold, "n_bets": 0,
                "staked": 0.0, "profit": 0.0, "roi": None, "hit_rate": None}

    # per placed bet: win -> (o-1)*stake, lose -> -stake
    profit = float(np.where(placed, np.where(won, (o - 1.0) * stake, -stake), 0.0).sum())
    staked = float(n_bets * stake)
    hits = int((placed & won).sum())
    return {
        "mode": mode,
        "threshold": threshold if mode == "value_threshold" else None,
        "n_bets": n_bets,
        "staked": staked,
        "profit": round(profit, 4),
        "roi": round(profit / staked, 6),
        "hit_rate": round(hits / n_bets, 6),
    }
