"""Generic, pluggable feature-consuming baseline (Predictor protocol).

Two-layer design:
  TabularEstimator -- the pluggable inner contract, deliberately shaped to
  match the sklearn classifier convention (fit(X, y), predict_proba(X),
  classes_) so LogisticRegression, gradient boosting, XGBoost, LightGBM and
  CatBoost's sklearn-compatible classes all satisfy it with zero adapter
  code.
  TabularPredictor -- the outer Predictor-protocol implementer. Owns
  feature-column allowlisting, preprocessing (impute + one-hot league_key +
  scale, fit on train only), one estimator per market, and reindexing
  estimator output into BacktestRunner's required selection order.

Feature-group column resolution is intentionally NOT derived by re-running
each FeatureGroup.build() -- that needs the raw pre-feature match frame,
which this class never sees (it only sees the already-built dataset frame,
same convention as DixonColesPredictor.fit(train)). Instead each supported
group's exact column-naming logic is mirrored here from that group's own
published constants (ROLLING_WINDOWS, MARKET_SELECTIONS, BOOKMAKERS,
DEVIG_METHODS) -- a true allowlist derived from source-of-truth constants,
not a guess, and it stays in sync automatically if those constants change.
This is the leakage safeguard: identity/target/raw-odds columns can never
enter this allowlist even though they sit in the same frame, because they
don't match any known feature group's naming scheme.

Pools across leagues (league_key as a one-hot feature) rather than fitting
one model per league like DixonColesPredictor -- maximizes use of the
training data the M1/M2 data-expansion work grew, and every supported
estimator class handles a categorical league feature natively or via
one-hot.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Protocol, Sequence

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from footpred.ml.backtest.runner import MARKETS
from footpred.ml.features.odds_features import (
    BOOKMAKERS, DEVIG_METHODS, DIVERGENCE_METHOD, MARKET_SELECTIONS,
)
from footpred.ml.features.team_form import ROLLING_WINDOWS

LEAGUE_COL = "league_key"


class TabularEstimator(Protocol):
    """The pluggable inner contract -- deliberately the sklearn classifier
    shape (fit/predict_proba/classes_), so sklearn/XGBoost/LightGBM/CatBoost
    classifiers all satisfy it without adapter code."""
    classes_: Sequence[str]

    def fit(self, X: np.ndarray, y: np.ndarray) -> "TabularEstimator": ...
    def predict_proba(self, X: np.ndarray) -> np.ndarray: ...


def _odds_core_columns() -> List[str]:
    """Mirrors OddsFeatureGroup's exact naming scheme (odds_features.py)."""
    cols: List[str] = []
    for market, sels in MARKET_SELECTIONS.items():
        mkt = market.replace(".", "_")
        for book in BOOKMAKERS:
            for s in sels:
                cols.append(f"imp_{mkt}_{s}_{book}_raw")
            cols.append(f"ovr_{mkt}_{book}")
            for method in DEVIG_METHODS:
                for s in sels:
                    cols.append(f"devig_{mkt}_{s}_{book}_{method}")
        for s in sels:
            cols.append(f"div_{mkt}_{s}_{DIVERGENCE_METHOD}")
    return cols


def _team_form_columns() -> List[str]:
    """Mirrors TeamFormFeatureGroup's exact naming scheme (team_form.py)."""
    stats = ("pts", "gf", "ga", "gd", "n")
    cols: List[str] = []
    for side in ("home", "away"):
        for w in ROLLING_WINDOWS:
            for stat in stats:
                cols.append(f"{side}_form_{stat}_last{w}")
    return cols


_KNOWN_GROUP_COLUMNS: Dict[str, Callable[[], List[str]]] = {
    "odds_core": _odds_core_columns,
    "team_form": _team_form_columns,
}


def resolve_feature_columns(frame: pd.DataFrame, feature_groups: Sequence[str]) -> List[str]:
    """Explicit allowlist: only columns belonging to a KNOWN feature group's
    own deterministic naming scheme, intersected with what's actually present
    in ``frame``. Never derived by exclusion -- a new identity/target column
    added upstream can never silently become a "feature" through this path."""
    resolved: List[str] = []
    for name in feature_groups:
        if name not in _KNOWN_GROUP_COLUMNS:
            raise KeyError(
                f"unsupported feature group for TabularPredictor: {name!r}; "
                f"have {sorted(_KNOWN_GROUP_COLUMNS)}")
        expected = _KNOWN_GROUP_COLUMNS[name]()
        present = [c for c in expected if c in frame.columns]
        if not present:
            raise ValueError(
                f"feature group {name!r} resolved to zero columns present in the "
                f"frame -- check the frame was built with this group registered")
        resolved.extend(present)
    return resolved


class TabularPredictor:
    """Predictor-protocol implementer: a generic, pluggable feature-consuming
    baseline. One ``estimator_factory()``-produced model per market, sharing
    one preprocessing pipeline fit once on train (median-impute numeric
    features, one-hot encode league_key, then scale -- scaling matters for
    L2-regularized linear estimators specifically, where raw feature scales
    would otherwise distort the penalty unevenly)."""

    def __init__(
        self,
        feature_groups: Sequence[str],
        estimator_factory: Callable[[], TabularEstimator],
        name: str = "Tabular",
    ):
        self.feature_groups = list(feature_groups)
        self._estimator_factory = estimator_factory
        self.name = name
        self._preprocessor: ColumnTransformer | None = None
        self._feature_cols: List[str] = []
        self._known_leagues: List[str] = []
        self._estimators: Dict[str, TabularEstimator] = {}
        self._class_order: Dict[str, List[str]] = {}

    def fit(self, train: pd.DataFrame) -> "TabularPredictor":
        self._feature_cols = resolve_feature_columns(train, self.feature_groups)
        self._known_leagues = sorted(train[LEAGUE_COL].dropna().unique().tolist())

        numeric_pipeline = Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ])
        self._preprocessor = ColumnTransformer([
            ("numeric", numeric_pipeline, self._feature_cols),
            ("league", OneHotEncoder(categories=[self._known_leagues], handle_unknown="ignore"),
             [LEAGUE_COL]),
        ])
        X = self._preprocessor.fit_transform(train)

        self._estimators = {}
        self._class_order = {}
        for market, meta in MARKETS.items():
            target_col = meta["target"]
            if target_col not in train.columns:
                continue
            y_full = train[target_col]
            mask = y_full.notna().to_numpy()
            if mask.sum() == 0:
                continue
            estimator = self._estimator_factory()
            estimator.fit(X[mask], y_full[mask].to_numpy())
            self._estimators[market] = estimator
            self._class_order[market] = list(estimator.classes_)
        return self

    def predict_proba(self, market: str, X: pd.DataFrame) -> pd.DataFrame:
        if market not in MARKETS:
            raise KeyError(f"unknown market {market!r}; have {sorted(MARKETS)}")
        sels = MARKETS[market]["selections"]
        out = pd.DataFrame(index=X.index, columns=sels, dtype=float)

        estimator = self._estimators.get(market)
        if estimator is None:
            return out  # market never fit (no target at train time) -> abstain entirely

        # league unseen at train time -> abstain, same convention as
        # DixonColesPredictor's unseen-team/league abstention. Deliberately
        # NOT abstaining on an unseen team: team identity isn't a raw
        # feature here, only aggregated team_form stats are, and those
        # already degrade gracefully (imputed) for a team's first-ever match.
        unseen_league = ~X[LEAGUE_COL].isin(self._known_leagues)

        Xt = self._preprocessor.transform(X)
        raw = estimator.predict_proba(Xt)
        raw_df = pd.DataFrame(raw, index=X.index, columns=self._class_order[market])
        reindexed = raw_df.reindex(columns=sels)
        reindexed.loc[unseen_league.to_numpy()] = np.nan
        return reindexed
