"""Odds-derived features (feature group "odds_core", v1.0).

Per market x bookmaker, when all selections of that market are quoted:
  imp_<mkt>_<sel>_<book>_raw          raw implied probability (1/odds)
  ovr_<mkt>_<book>                    overround (booksum - 1)
  devig_<mkt>_<sel>_<book>_<method>   de-vigged probability, every method
  div_<mkt>_<sel>_<method>            bet365 minus market_avg de-vigged
                                      probability (consensus disagreement),
                                      computed on de-vigged values so
                                      bookmaker margin never masquerades
                                      as signal
All values NaN where the market isn't fully quoted for that bookmaker.
"""
from __future__ import annotations

import math
from typing import Dict, List

import numpy as np
import pandas as pd

from footpred.domain.entities import Bookmaker
from footpred.infra.read_models import odds_col
from footpred.ml.features.base import FeatureContext, register_feature_group
from footpred.ml.odds_math import devig, implied_probabilities, overround

MARKET_SELECTIONS: Dict[str, List[str]] = {
    "1x2": ["home", "draw", "away"],
    "ou_2.5": ["over", "under"],
}
BOOKMAKERS = [Bookmaker.BET365.value, Bookmaker.MARKET_AVG.value]
DEVIG_METHODS = ["proportional", "power", "shin"]  # frozen column set for v1.0
DIVERGENCE_METHOD = "shin"


def _mk(market: str) -> str:
    return market.replace(".", "_")


class OddsFeatureGroup:
    name = "odds_core"
    version = "1.0"

    def build(self, ctx: FeatureContext) -> pd.DataFrame:
        df = ctx.matches
        out = pd.DataFrame(index=df["match_id"])

        for market, sels in MARKET_SELECTIONS.items():
            mkt = _mk(market)
            for book in BOOKMAKERS:
                cols = [odds_col(market, s, book) for s in sels]
                if not all(c in df.columns for c in cols):
                    continue
                odds_mat = df[cols].to_numpy(dtype=float)
                n = len(df)
                raw = np.full((n, len(sels)), np.nan)
                ovr = np.full(n, np.nan)
                dv = {m: np.full((n, len(sels)), np.nan) for m in DEVIG_METHODS}
                for i in range(n):
                    row = odds_mat[i]
                    if np.isnan(row).any() or (row < 1.01).any():
                        continue  # market not (validly) fully quoted
                    imp = implied_probabilities(row.tolist())
                    raw[i] = imp
                    ovr[i] = overround(imp)
                    for method in DEVIG_METHODS:
                        dv[method][i] = devig(imp, method)
                for j, s in enumerate(sels):
                    out[f"imp_{mkt}_{s}_{book}_raw"] = raw[:, j].tolist()
                out[f"ovr_{mkt}_{book}"] = ovr.tolist()
                for method in DEVIG_METHODS:
                    for j, s in enumerate(sels):
                        out[f"devig_{mkt}_{s}_{book}_{method}"] = dv[method][:, j].tolist()

            # divergence: bet365 minus market average, de-vigged
            b365 = Bookmaker.BET365.value
            avg = Bookmaker.MARKET_AVG.value
            for s in sels:
                c1 = f"devig_{mkt}_{s}_{b365}_{DIVERGENCE_METHOD}"
                c2 = f"devig_{mkt}_{s}_{avg}_{DIVERGENCE_METHOD}"
                if c1 in out.columns and c2 in out.columns:
                    out[f"div_{mkt}_{s}_{DIVERGENCE_METHOD}"] = out[c1] - out[c2]
        return out


register_feature_group(OddsFeatureGroup())
