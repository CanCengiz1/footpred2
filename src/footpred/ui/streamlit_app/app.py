"""Streamlit UI for Sprint 1: dataset import + report + DB overview.

Thin adapter: talks only to ImportService. No business logic lives here.
Run:  streamlit run src/footpred/ui/streamlit_app/app.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from footpred.infra.db.session import make_session_factory
from footpred.infra.db.uow import SqlAlchemyUnitOfWork
from footpred.ingest.mapping import BUILTIN_PROFILES, load_profile
from footpred.services.import_service import ImportService

PROFILE_DIR = Path("configs/mapping_profiles")


@st.cache_resource
def get_service() -> ImportService:
    factory = make_session_factory()
    profiles = list(BUILTIN_PROFILES)
    if PROFILE_DIR.exists():
        for p in sorted(PROFILE_DIR.glob("*.json")):
            try:
                profiles.append(load_profile(p))
            except Exception as e:  # noqa: BLE001 - surface bad profiles, don't crash
                st.warning(f"Skipping invalid profile {p.name}: {e}")
    return ImportService(lambda: SqlAlchemyUnitOfWork(factory), profiles)


def render_report(report) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rows", report.rows_total)
    c2.metric("Imported", report.rows_imported)
    c3.metric("Duplicates", report.rows_duplicate)
    c4.metric("Enriched", report.rows_enriched)
    c5.metric("Rejected", report.rows_rejected)
    st.caption(f"Odds quotes stored: {report.odds_quotes_stored} "
               f"· backfilled onto already-known matches: {report.odds_quotes_backfilled}")

    if report.rejections:
        st.subheader("Rejected rows")
        st.dataframe(pd.DataFrame(report.rejections), width="stretch")
    if report.warnings:
        st.subheader("Warnings")
        st.dataframe(pd.DataFrame(report.warnings), width="stretch")
    if report.resolutions:
        st.subheader("Team resolutions to review (fuzzy matches / new teams)")
        st.dataframe(pd.DataFrame(report.resolutions), width="stretch")
    if not (report.rejections or report.warnings or report.resolutions):
        st.success("Clean import — no issues to review.")


def main() -> None:
    st.set_page_config(page_title="FootPred — Import", layout="wide")
    st.title("FootPred · Historical Data Import")
    service = get_service()

    with st.sidebar:
        st.header("Database")
        summary = service.database_summary()
        st.metric("Matches", summary["matches"])
        st.metric("Odds quotes", summary["odds_quotes"])
        if summary["leagues"]:
            st.dataframe(pd.DataFrame(summary["leagues"]), width="stretch")
        if summary["imports"]:
            st.subheader("Import history")
            st.dataframe(pd.DataFrame(summary["imports"]), width="stretch")

    uploaded = st.file_uploader("Upload a historical dataset (CSV / Excel)",
                                type=["csv", "txt", "xlsx", "xls", "xlsm"])
    if uploaded is None:
        st.info("Upload a file to begin. football-data.co.uk layouts are "
                "auto-detected; other layouts can use JSON mapping profiles in "
                "configs/mapping_profiles/.")
        return

    preview, df = service.preview(uploaded, uploaded.name)
    st.subheader("Preview")
    st.dataframe(preview.head, width="stretch")
    st.caption(f"{preview.row_count} rows · columns: {', '.join(preview.columns[:20])}"
               + (" …" if len(preview.columns) > 20 else ""))

    names = [p.name for p in service.profiles]
    default_idx = 0
    if preview.detected_profile is not None:
        default_idx = names.index(preview.detected_profile.name)
        if preview.auto_apply:
            st.success(f"Detected profile: **{preview.detected_profile.name}** "
                       f"(score {preview.detection_score:.2f})")
        else:
            st.warning(f"Best guess: {preview.detected_profile.name} "
                       f"(score {preview.detection_score:.2f}) — core columns "
                       "missing, please verify.")
    chosen = st.selectbox("Mapping profile", names, index=default_idx)
    profile = next(p for p in service.profiles if p.name == chosen)

    missing = profile.missing_core_columns(preview.columns)
    if missing:
        st.error(
            f"Profile **{profile.name}** expects core columns this file "
            f"lacks: `{', '.join(missing)}`. Importing would reject every "
            "row — fix the file or choose/create a matching profile."
        )

    if st.button("Import", type="primary", disabled=bool(missing)):
        with st.spinner("Importing..."):
            report = service.import_dataframe(df, uploaded.name, profile)
        st.divider()
        render_report(report)
        st.caption("Sidebar totals refresh on the next interaction.")


if __name__ == "__main__":
    main()
