"""Model-ready dataset generation.

DatasetBuilder assembles: identity + targets + registered feature groups +
temporal split labels, runs the leakage guard, and produces a versioned file
artifact (Parquet, CSV fallback) with a JSON manifest.

Datasets are file artifacts, NOT database tables: features are deterministic
derivations of stored data, and persisting them in SQLite would create a
second source of truth that silently rots when derivation logic changes.

Versioning (Sprint-2 review point 7):
- SCHEMA_VERSION: structure of the dataset itself (identity/target columns,
  manifest layout). Bumped on breaking changes.
- Each feature group carries its own version, recorded per group in the
  manifest with its exact column list.
- content_hash: sha256 over the canonicalized frame — two builds match iff
  their bytes match.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

import footpred.ml.features  # noqa: F401  (registers built-in groups)
from footpred.infra.read_models import MatchOddsReader
from footpred.ml.features.base import FeatureContext, get_feature_group
from footpred.ml.splits import SingleSplitStrategy, assert_no_leakage
from footpred.ml.targets import label_1x2, label_btts, label_htft, label_ou25

SCHEMA_VERSION = "2.0"

IDENTITY_COLS = ["match_id", "league_key", "league", "match_date", "has_ht"]
TARGET_COLS = ["target_1x2", "target_ou_2_5", "target_btts", "target_htft"]


@dataclass
class DatasetManifest:
    schema_version: str
    dataset_id: str
    created_at: str
    feature_groups: List[dict]
    split: dict
    rows: dict
    content_hash: str
    file_format: str
    filename: str
    extra: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, ensure_ascii=False)


class DatasetBuilder:
    def __init__(
        self,
        reader: MatchOddsReader,
        feature_groups: Sequence[str],
        split: SingleSplitStrategy,
        leakage_group_col: Optional[str] = "league_key",
    ):
        self._reader = reader
        self._group_names = list(feature_groups)
        self._split = split
        self._leakage_group_col = leakage_group_col

    def build(self) -> Tuple[pd.DataFrame, Dict]:
        base = self._reader.load_completed()
        if base.empty:
            raise ValueError("no completed matches in the database")

        frame = base[IDENTITY_COLS].copy()
        frame["target_1x2"] = [
            label_1x2(h, a) for h, a in zip(base["ft_home"], base["ft_away"])]
        frame["target_ou_2_5"] = [
            label_ou25(h, a) for h, a in zip(base["ft_home"], base["ft_away"])]
        frame["target_btts"] = [
            label_btts(h, a) for h, a in zip(base["ft_home"], base["ft_away"])]
        frame["target_htft"] = [
            label_htft(hh, ha, fh, fa)
            for hh, ha, fh, fa in zip(base["ht_home"], base["ht_away"],
                                      base["ft_home"], base["ft_away"])]

        ctx = FeatureContext(matches=base)
        group_meta: List[dict] = []
        for name in self._group_names:
            group = get_feature_group(name)
            feats = group.build(ctx)
            overlap = set(feats.columns) & set(frame.columns)
            if overlap:
                raise ValueError(f"feature group {name!r} collides on {sorted(overlap)}")
            frame = frame.merge(feats, left_on="match_id", right_index=True, how="left")
            group_meta.append({"name": group.name, "version": group.version,
                               "columns": sorted(feats.columns)})

        labels = self._split.assign(frame)
        assert_no_leakage(frame, labels, group_col=self._leakage_group_col)
        frame["split"] = labels

        # raw bet365/avg odds columns travel along for the betting simulator
        odds_cols = [c for c in base.columns if c.startswith("odds_")]
        frame = frame.merge(base[["match_id", *odds_cols]], on="match_id", how="left")

        frame = frame.sort_values("match_id").reset_index(drop=True)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "feature_groups": group_meta,
            "split": self._split.describe(),
            "rows": {
                "total": int(len(frame)),
                "train": int((frame["split"] == "train").sum()),
                "test": int((frame["split"] == "test").sum()),
                "per_league": {str(k): int(v) for k, v in
                               frame.groupby("league_key").size().items()},
                "with_ht": int(frame["has_ht"].sum()),
            },
            "content_hash": content_hash(frame),
        }
        return frame, manifest


def content_hash(frame: pd.DataFrame) -> str:
    canon = frame.sort_values("match_id")[sorted(frame.columns)]
    return hashlib.sha256(
        canon.to_csv(index=False, float_format="%.10g").encode("utf-8")
    ).hexdigest()


def save_dataset(frame: pd.DataFrame, manifest: Dict, out_dir: str | Path) -> Path:
    """Write artifact + manifest. Parquet preferred; CSV fallback recorded
    in the manifest so consumers never guess."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dataset_id = (datetime.utcnow().strftime("%Y%m%dT%H%M%S")
                  + "-" + manifest["content_hash"][:8])
    try:
        filename = f"dataset-{dataset_id}.parquet"
        frame.to_parquet(out / filename, index=False)
        file_format = "parquet"
    except (ImportError, ValueError):
        filename = f"dataset-{dataset_id}.csv"
        frame.to_csv(out / filename, index=False)
        file_format = "csv"

    full = DatasetManifest(
        schema_version=manifest["schema_version"], dataset_id=dataset_id,
        created_at=datetime.utcnow().isoformat(timespec="seconds"),
        feature_groups=manifest["feature_groups"], split=manifest["split"],
        rows=manifest["rows"], content_hash=manifest["content_hash"],
        file_format=file_format, filename=filename,
    )
    (out / f"dataset-{dataset_id}.manifest.json").write_text(
        full.to_json(), encoding="utf-8")
    return out / filename


def load_dataset(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
