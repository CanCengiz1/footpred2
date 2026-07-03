"""Evaluation metrics for probabilistic predictions. No sklearn dependency —
implemented from definitions, verified against hand-computed values in tests.

Inputs: probs is an (n, k) DataFrame whose columns are selections; outcomes
is a length-n Series of realized selection strings.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

_EPS = 1e-12


def _aligned(probs: pd.DataFrame, outcomes: pd.Series) -> np.ndarray:
    """One-hot matrix of outcomes in the probs column order."""
    cols = list(probs.columns)
    unknown = set(outcomes.unique()) - set(cols)
    if unknown:
        raise ValueError(f"outcomes contain selections not in probs: {unknown}")
    idx = outcomes.map({c: i for i, c in enumerate(cols)}).to_numpy()
    onehot = np.zeros((len(outcomes), len(cols)))
    onehot[np.arange(len(outcomes)), idx] = 1.0
    return onehot


def log_loss(probs: pd.DataFrame, outcomes: pd.Series) -> float:
    """Mean negative log-likelihood (natural log)."""
    p = np.clip(probs.to_numpy(dtype=float), _EPS, 1.0)
    onehot = _aligned(probs, outcomes)
    return float(-(onehot * np.log(p)).sum(axis=1).mean())


def brier_score(probs: pd.DataFrame, outcomes: pd.Series) -> float:
    """Multiclass Brier: mean squared distance to the one-hot outcome."""
    p = probs.to_numpy(dtype=float)
    onehot = _aligned(probs, outcomes)
    return float(((p - onehot) ** 2).sum(axis=1).mean())


def calibration_table(
    probs: pd.DataFrame, outcomes: pd.Series, n_bins: int = 10
) -> Dict:
    """Pooled one-vs-rest reliability table + expected calibration error.

    Every (match, selection) pair contributes one (predicted p, hit) point;
    points are binned by predicted probability. Perfect calibration puts
    observed frequency == mean predicted probability in every bin.
    """
    p = probs.to_numpy(dtype=float).ravel()
    hits = _aligned(probs, outcomes).ravel()
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    which = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)

    rows: List[dict] = []
    ece = 0.0
    for b in range(n_bins):
        mask = which == b
        n = int(mask.sum())
        if n == 0:
            rows.append({"bin": f"{edges[b]:.1f}-{edges[b+1]:.1f}", "n": 0,
                         "mean_predicted": None, "observed_freq": None})
            continue
        mp, of = float(p[mask].mean()), float(hits[mask].mean())
        rows.append({"bin": f"{edges[b]:.1f}-{edges[b+1]:.1f}", "n": n,
                     "mean_predicted": round(mp, 4), "observed_freq": round(of, 4)})
        ece += (n / len(p)) * abs(mp - of)
    return {"bins": rows, "ece": round(float(ece), 6), "n_points": int(len(p))}
