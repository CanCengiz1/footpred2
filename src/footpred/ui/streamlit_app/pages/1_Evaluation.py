"""Evaluation page (Sprint 2): build model-ready datasets and run the
market-baseline backtest with the de-vig comparison table.

Thin adapter — talks only to EvaluationService.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from footpred.infra.db.session import make_session_factory
from footpred.infra.read_models import SqlMatchOddsReader
from footpred.ml.backtest.runner import MARKETS
from footpred.services.evaluation_service import EvaluationService


@st.cache_resource
def get_service() -> EvaluationService:
    return EvaluationService(SqlMatchOddsReader(make_session_factory()))


def main() -> None:
    st.set_page_config(page_title="FootPred — Evaluation", layout="wide")
    st.title("FootPred · Dataset & Market Baseline Evaluation")
    service = get_service()

    st.subheader("1 · Build model-ready dataset")
    train_frac = st.slider("Train fraction (per league, temporal)",
                           0.5, 0.9, 0.7, 0.05)
    if st.button("Build dataset", type="primary"):
        with st.spinner("Building features, splitting, hashing..."):
            frame, manifest, path = service.build_dataset(train_frac=train_frac)
        st.session_state["dataset"] = frame
        st.session_state["manifest"] = manifest
        st.success(f"Dataset built and saved: `{path}`")

    manifest = st.session_state.get("manifest")
    if manifest:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Rows", manifest["rows"]["total"])
        c2.metric("Train", manifest["rows"]["train"])
        c3.metric("Test", manifest["rows"]["test"])
        c4.metric("With HT", manifest["rows"]["with_ht"])
        with st.expander("Manifest (versions, feature groups, hash)"):
            st.json(manifest)

    frame = st.session_state.get("dataset")
    if frame is None:
        st.info("Build a dataset to enable the backtest.")
        return

    st.subheader("2 · Market baseline backtest (B0)")
    market = st.selectbox("Market", sorted(MARKETS))
    theta = st.number_input("Value threshold θ", 0.0, 0.2, 0.02, 0.01,
                            format="%.2f")
    if st.button("Run backtest"):
        with st.spinner("Scoring B0 under every de-vig method..."):
            reports = service.run_baseline_backtests(
                frame, market, value_threshold=theta)
        st.session_state["reports"] = reports

    reports = st.session_state.get("reports")
    if not reports:
        return

    st.markdown("**De-vig method comparison** (lower log loss / Brier / ECE "
                "is better; this table arbitrates the default method "
                "empirically)")
    st.dataframe(EvaluationService.comparison_table(reports), width="stretch")

    for r in reports:
        with st.expander(f"{r.model} — details"):
            st.write({"scored": r.n_rows_scored,
                      "available": r.n_rows_available,
                      "notes": r.notes})
            st.markdown("*Calibration (pooled one-vs-rest)*")
            st.dataframe(pd.DataFrame(r.calibration["bins"]), width="stretch")
            st.caption(f"ECE: {r.calibration['ece']}")
            st.markdown("*Betting simulations (flat stake)*")
            st.dataframe(pd.DataFrame(r.simulations), width="stretch")
    st.caption(
        "Sanity expectations for B0 vs. its own prices: value rule ≈ 0 bets "
        "(proportional: exactly 0); bet-all ROI ≈ −overround. If B0 looks "
        "profitable against itself, the harness is broken — report it."
    )


main()
