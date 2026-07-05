"""Persistence for the Canonical Prediction Engine's output.

Long-format, mirroring the `odds` table's own (bookmaker, market, selection,
price) shape and its documented reason (README: "new markets need no schema
change"). A prediction's row count varies with the market's own outcome
cardinality (2 for btts, 3 for 1x2, 9 for htft, ...), so a wide fixed-column
schema would need a migration per market; long format never does.

Backtest mode only (see docs/VISION.md): output is a fully re-derivable file
artifact (historical data + a fixed model/evidence-tier configuration),
following DatasetBuilder's own manifest + content_hash convention -- not a DB
table. The DB table is reserved for live mode (immutable point-in-time facts
that can never be safely regenerated), designed in docs/VISION.md but not
built in this milestone.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Sequence

import pandas as pd

from footpred.ml.backtest.runner import MARKETS
from footpred.ml.evidence import Finding, TIER_WEIGHTS
from footpred.ml.models.canonical import CanonicalPredictor, Contribution

SCHEMA_VERSION = "1.0"
ROLES = ("baseline", "canonical", "counterfactual")
COLUMNS = ["match_id", "market", "kind", "role", "finding_id", "tier", "weight",
           "model_hash", "selection", "value"]


def model_fingerprint(contribution: Contribution) -> str:
    """A reproducibility fingerprint for one live finding's fitted
    with-finding model, computed over its own predictions on this exact
    input batch -- deliberately NOT by pickling the live model object.
    TabularPredictor stores the caller's ``estimator_factory`` as an
    instance attribute, and that is very often (including in this
    codebase's own tests) an unpicklable lambda -- pickling the whole object
    would fail for essentially any real caller. Fingerprinting the model's
    own output instead sidesteps that entirely, is provider-agnostic (works
    for any Predictor, not just TabularPredictor), and is arguably the more
    correct thing anyway: if this hash differs between two runs over the
    same input, something about what the model actually *computes* changed
    -- a fitted parameter, a code change, a library version -- which is
    exactly what a reproducibility fingerprint needs to catch. Same
    content_hash CSV-serialization convention as datasets.py, for
    consistency."""
    canon = contribution.with_finding_probs.sort_index()
    canon = canon[sorted(canon.columns)]
    return hashlib.sha256(
        canon.to_csv(index=True, float_format="%.10g").encode("utf-8")
    ).hexdigest()


def build_predictions_frame(engine: CanonicalPredictor, market: str, X: pd.DataFrame) -> pd.DataFrame:
    """One row per (match_id, market, selection) for each of
    baseline/canonical/counterfactual (``kind="value"``, distinguished by
    ``role``), plus one row per (match_id, finding_id, selection) for each
    live finding's isolated, unweighted logit delta (``kind="contribution"``).
    ``match_id`` is taken from X's index, the same identity convention every
    other frame in this codebase uses (see ``IDENTITY_COLS`` in datasets.py).
    """
    sels = MARKETS[market]["selections"]
    explained = engine.explain(market, X)
    model_hashes = {c.finding_id: model_fingerprint(c) for c in explained["contributions"]}

    rows: List[dict] = []
    for role in ROLES:
        probs = explained[role]
        for match_id, row in probs.iterrows():
            for sel in sels:
                v = row[sel]
                rows.append({
                    "match_id": match_id, "market": market, "kind": "value",
                    "role": role, "finding_id": None, "tier": None, "weight": None,
                    "model_hash": None, "selection": sel,
                    "value": float(v) if pd.notna(v) else None,
                })
    for c in explained["contributions"]:
        for match_id, row in c.delta.iterrows():
            for sel in sels:
                v = row[sel]
                rows.append({
                    "match_id": match_id, "market": market, "kind": "contribution",
                    "role": None, "finding_id": c.finding_id, "tier": c.tier,
                    "weight": c.weight, "model_hash": model_hashes.get(c.finding_id),
                    "selection": sel, "value": float(v) if pd.notna(v) else None,
                })

    frame = pd.DataFrame(rows, columns=COLUMNS)
    return frame.sort_values(
        ["match_id", "kind", "role", "finding_id", "selection"], na_position="first"
    ).reset_index(drop=True)


def content_hash(frame: pd.DataFrame) -> str:
    canon = frame.sort_values(
        ["match_id", "market", "kind", "role", "finding_id", "selection"], na_position="first"
    )[sorted(frame.columns)]
    return hashlib.sha256(
        canon.to_csv(index=False, float_format="%.10g").encode("utf-8")
    ).hexdigest()


def save_predictions(
    frame: pd.DataFrame, findings: Sequence[Finding], out_dir: str | Path,
    mode: str = "backtest",
) -> Path:
    """Write artifact + manifest, mirroring ``datasets.save_dataset``
    exactly: Parquet preferred, CSV fallback recorded in the manifest, a
    content-hashed id, and the full findings-registry snapshot + tier-weight
    table captured at generation time -- so a later change to either can
    never silently reinterpret a past prediction (see docs/VISION.md's
    reproducibility requirement)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    chash = content_hash(frame)
    pred_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S") + "-" + chash[:8]

    contrib_rows = frame[frame["kind"] == "contribution"]
    model_hashes = (
        contrib_rows.drop_duplicates("finding_id").set_index("finding_id")["model_hash"].to_dict()
        if not contrib_rows.empty else {}
    )

    try:
        filename = f"predictions-{pred_id}.parquet"
        frame.to_parquet(out / filename, index=False)
        file_format = "parquet"
    except (ImportError, ValueError):
        filename = f"predictions-{pred_id}.csv"
        frame.to_csv(out / filename, index=False)
        file_format = "csv"

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "prediction_id": pred_id,
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
        "mode": mode,
        "tier_weights": TIER_WEIGHTS,
        "findings_registry_snapshot": [asdict(f) for f in findings],
        "model_hashes": model_hashes,
        "content_hash": chash,
        "file_format": file_format,
        "filename": filename,
        "rows": int(len(frame)),
    }
    (out / f"predictions-{pred_id}.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return out / filename


def load_predictions(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
