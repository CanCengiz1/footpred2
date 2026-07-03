"""B0 — the market baseline: de-vigged bookmaker probabilities ARE the
prediction. The benchmark every model must beat; decades of literature say
beating it after the margin is rare, which is exactly why it goes first.

Reads devig_* feature columns (Bet365 primary, market-average fallback per
row) — it consumes the same dataset artifact as any future model and plugs
into the same Predictor interface.
"""
from __future__ import annotations

import pandas as pd

from footpred.domain.entities import Bookmaker
from footpred.ml.backtest.runner import MARKETS


class MarketBaseline:
    def __init__(self, devig_method: str = "shin",
                 primary: str = Bookmaker.BET365.value,
                 fallback: str = Bookmaker.MARKET_AVG.value):
        self._method = devig_method
        self._primary = primary
        self._fallback = fallback
        self.name = f"B0-market[{devig_method}]"

    def predict_proba(self, market: str, X: pd.DataFrame) -> pd.DataFrame:
        sels = MARKETS[market]["selections"]
        mkt = market.replace(".", "_")
        out = pd.DataFrame(index=X.index, columns=sels, dtype=float)
        for s in sels:
            pcol = f"devig_{mkt}_{s}_{self._primary}_{self._method}"
            fcol = f"devig_{mkt}_{s}_{self._fallback}_{self._method}"
            p = X[pcol] if pcol in X.columns else pd.Series(float("nan"), index=X.index)
            f = X[fcol] if fcol in X.columns else pd.Series(float("nan"), index=X.index)
            out[s] = p.fillna(f)
        # a row must come entirely from one bookmaker's coherent distribution;
        # mixed rows could sum != 1 -> renormalize defensively, abstain if bad
        totals = out.sum(axis=1)
        bad = (totals - 1.0).abs() > 1e-6
        out.loc[bad] = out.loc[bad].div(totals[bad], axis=0)
        return out
