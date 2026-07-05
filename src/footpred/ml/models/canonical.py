"""Canonical Prediction Engine -- the mechanism from docs/VISION.md that
blends the promoted baseline with evidence-tier-weighted contributions from
live findings into one canonical FootPred prediction, via logarithmic
opinion pooling (a weighted sum in logit space, renormalized by softmax).

A finding's "contribution" is exactly the incremental logit-space delta a
Stage 2 ablation already measures (the with-finding model's prediction minus
the baseline's), kept around as a reusable object instead of a one-off
analysis result -- no new modeling assumption is introduced here.

Market-agnostic by construction (see docs/VISION.md): every quantity is
indexed by MARKETS[market]["selections"], never a hardcoded outcome set --
adding a new market (btts, htft, ...) needs no change to this module, only
an entry in MARKETS and, if a finding applies to it, a registry entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

import numpy as np
import pandas as pd

from footpred.ml.backtest.runner import MARKETS
from footpred.ml.evidence import Finding, live_findings
from footpred.ml.models.tabular import TabularEstimator, TabularPredictor

EPS = 1e-10


def _to_logit(probs: pd.DataFrame) -> pd.DataFrame:
    """log(p), clipped away from 0. An additive per-row constant is
    irrelevant after softmax renormalizes, so plain log(p) -- not the
    classic single log-odds ratio -- is the right generalization to an
    arbitrary number of selections (2 for btts, 3 for 1x2, 9 for htft, ...)."""
    return np.log(probs.clip(lower=EPS))


def _softmax_rows(logits: pd.DataFrame) -> pd.DataFrame:
    shifted = logits.sub(logits.max(axis=1), axis=0)  # numerical stability
    exp = np.exp(shifted)
    return exp.div(exp.sum(axis=1), axis=0)


@dataclass
class Contribution:
    """One live finding's isolated effect on a batch of predictions.
    ``delta`` is logged raw (NaN where the finding's own model abstained,
    e.g. an unseen league) -- distinct from how it is *applied* to the
    blend, where an abstaining finding contributes zero, never NaN."""
    finding_id: str
    tier: str
    weight: float
    delta: pd.DataFrame  # logit-space delta, columns = market selections, raw (may contain NaN)
    with_finding_probs: pd.DataFrame  # the with-finding model's own raw prediction, for fingerprinting


class CanonicalPredictor:
    """Predictor-protocol implementer (name + predict_proba(market, X)) so it
    plugs into BacktestRunner unchanged -- the same discipline every model
    since Dixon-Coles has kept. ``explain`` returns the full audit record the
    reproducibility log needs (baseline, canonical, the internal
    promoted-only counterfactual, and each finding's isolated contribution) --
    none of which BacktestRunner or any user-facing caller ever sees.
    """

    name = "FootPred"

    def __init__(self, baseline, findings: Sequence[Finding],
                 estimator_factory: Callable[[], TabularEstimator]):
        """baseline: the promoted-baseline Predictor (today: MarketBaseline).
        findings: the full registry, unfiltered -- filtering by market/tier
        happens per call, so one instance serves every market.
        estimator_factory: how to build the "with-finding" TabularPredictor
        for each live finding -- same factory shape TabularPredictor itself
        takes, so any sklearn-compatible estimator works with zero new code.
        """
        self._baseline = baseline
        self._findings = list(findings)
        self._estimator_factory = estimator_factory
        self._finding_models: Dict[str, TabularPredictor] = {}

    def fit(self, train: pd.DataFrame) -> "CanonicalPredictor":
        """Fits one TabularPredictor per live finding (odds_core + that
        finding's own extra_columns) -- the exact "with-finding" ablation
        model each finding was validated with. A zero-weight finding
        (rejected / not_confirmed) is never fit at all."""
        self._finding_models = {}
        for f in self._findings:
            if not f.is_live:
                continue
            model = TabularPredictor(
                feature_groups=["odds_core"], extra_columns=f.extra_columns,
                estimator_factory=self._estimator_factory, name=f.finding_id,
            )
            model.fit(train)
            self._finding_models[f.finding_id] = model
        return self

    def _contributions(self, market: str, X: pd.DataFrame,
                        baseline_logit: pd.DataFrame) -> List[Contribution]:
        sels = MARKETS[market]["selections"]
        out: List[Contribution] = []
        for f in live_findings(self._findings, market):
            model = self._finding_models.get(f.finding_id)
            if model is None:
                continue  # registry changed after fit() -- be safe, not silently wrong
            with_finding_probs = model.predict_proba(market, X)
            delta = (_to_logit(with_finding_probs) - baseline_logit).reindex(columns=sels)
            out.append(Contribution(finding_id=f.finding_id, tier=f.tier, weight=f.weight,
                                     delta=delta, with_finding_probs=with_finding_probs))
        return out

    def explain(self, market: str, X: pd.DataFrame) -> Dict[str, object]:
        """Full audit record: baseline, canonical, the internal
        promoted-only counterfactual, and each live finding's isolated
        (unweighted) logit delta."""
        baseline_probs = self._baseline.predict_proba(market, X)
        baseline_logit = _to_logit(baseline_probs)
        contributions = self._contributions(market, X, baseline_logit)

        canonical_logit = baseline_logit.copy()
        counterfactual_logit = baseline_logit.copy()
        for c in contributions:
            applied = c.delta.fillna(0.0)  # an abstaining finding contributes zero, not NaN
            canonical_logit = canonical_logit + applied * c.weight
            if c.tier == "promoted":
                counterfactual_logit = counterfactual_logit + applied * 1.0

        # a row where the baseline itself abstained (any NaN selection) must
        # stay all-NaN end to end -- there is no floor below the anchor to
        # fall back to (see docs/VISION.md).
        abstained = baseline_probs.isna().any(axis=1)

        canonical = _softmax_rows(canonical_logit)
        counterfactual = _softmax_rows(counterfactual_logit)
        canonical.loc[abstained] = np.nan
        counterfactual.loc[abstained] = np.nan

        return {
            "baseline": baseline_probs,
            "canonical": canonical,
            "counterfactual": counterfactual,
            "contributions": contributions,
        }

    def predict_proba(self, market: str, X: pd.DataFrame) -> pd.DataFrame:
        return self.explain(market, X)["canonical"]
