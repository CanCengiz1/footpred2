"""CSV/Excel readers. Output: a pandas DataFrame with stripped column names.

Kept deliberately dumb: all semantics live in mapping/validation, so adding a
new physical format (parquet, API payload) later only touches this module.
"""
from __future__ import annotations

from pathlib import Path
from typing import IO, Union

import pandas as pd

Source = Union[str, Path, IO[bytes]]

_EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm"}


def read_table(source: Source, filename: str) -> pd.DataFrame:
    """Read a CSV or Excel file into a DataFrame.

    ``filename`` decides the format (needed because Streamlit uploads are
    in-memory buffers without a path).
    """
    suffix = Path(filename).suffix.lower()
    if suffix in _EXCEL_SUFFIXES:
        df = pd.read_excel(source)
    else:
        df = _read_csv_resilient(source)
    # scrub BOM defensively even for Excel/odd paths, then strip whitespace
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    return df


def _read_csv_resilient(source: Source) -> pd.DataFrame:
    """utf-8-sig first (transparently consumes the BOM that football-data
    and Excel-exported CSVs carry; identical to utf-8 when absent), latin-1
    fallback for legacy encodings. Delimiter sniffed by the python engine."""
    try:
        return pd.read_csv(source, sep=None, engine="python", encoding="utf-8-sig")
    except UnicodeDecodeError:
        if hasattr(source, "seek"):
            source.seek(0)  # type: ignore[union-attr]
        return pd.read_csv(source, sep=None, engine="python", encoding="latin-1")
