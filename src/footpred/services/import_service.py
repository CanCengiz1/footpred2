"""Application service: the only entry point the UI layer uses.

Owns the transaction boundary (one file == one unit of work == one commit).
UI never touches repositories, pipeline internals or SQLAlchemy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from footpred.domain.ports import UnitOfWork
from footpred.ingest.mapping import BUILTIN_PROFILES, MappingProfile, detect_profile
from footpred.ingest.pipeline import ImportPipeline, ImportReport
from footpred.ingest.readers import read_table

AUTO_APPLY_THRESHOLD = 0.7  # all core columns must be present


@dataclass
class ImportPreview:
    columns: List[str]
    head: pd.DataFrame
    row_count: int
    detected_profile: Optional[MappingProfile]
    detection_score: float

    @property
    def auto_apply(self) -> bool:
        return self.detected_profile is not None and self.detection_score >= AUTO_APPLY_THRESHOLD


class ImportService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        profiles: Optional[Sequence[MappingProfile]] = None,
    ):
        self._uow_factory = uow_factory
        self._profiles = list(profiles) if profiles else list(BUILTIN_PROFILES)

    @property
    def profiles(self) -> List[MappingProfile]:
        return list(self._profiles)

    def preview(self, source, filename: str) -> Tuple[ImportPreview, pd.DataFrame]:
        df = read_table(source, filename)
        profile, score = detect_profile(df.columns, self._profiles)
        preview = ImportPreview(
            columns=list(df.columns), head=df.head(10), row_count=len(df),
            detected_profile=profile, detection_score=score,
        )
        return preview, df

    def import_dataframe(
        self, df: pd.DataFrame, filename: str, profile: MappingProfile
    ) -> ImportReport:
        with self._uow_factory() as uow:
            report = ImportPipeline(uow, profile).run(df, filename)
            uow.commit()
        return report

    def import_file(self, source, filename: str, profile: MappingProfile) -> ImportReport:
        df = read_table(source, filename)
        return self.import_dataframe(df, filename, profile)

    # -- read-side summary for the UI dashboard ------------------------- #

    def database_summary(self) -> Dict:
        with self._uow_factory() as uow:
            leagues = {l.id: l for l in uow.leagues.all()}
            by_league = uow.matches.count_by_league()
            return {
                "matches": uow.matches.count(),
                "odds_quotes": uow.odds.count(),
                "leagues": [
                    {"league": leagues[lid].name if lid in leagues else str(lid),
                     "matches": n}
                    for lid, n in sorted(by_league.items(), key=lambda kv: -kv[1])
                ],
                "imports": [
                    {"file": r.filename, "profile": r.profile_name,
                     "imported": r.rows_imported, "duplicates": r.rows_duplicate,
                     "enriched": r.rows_enriched, "rejected": r.rows_rejected,
                     "at": str(r.created_at)}
                    for r in uow.imports.all()
                ],
            }
