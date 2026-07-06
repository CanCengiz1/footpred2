"""Import pipeline: read -> map -> validate -> resolve -> reconcile -> persist.

Reconciliation policy (identity vs. timing separated):

1. External ID (when the profile declares one): (source, external_id) hit
   -> duplicate. Perfect dedupe when sources provide IDs.
2. Natural key ``dedupe_key`` = league|home|away|date|time-or-NA:
   exact hit -> duplicate (score mismatch reported as a conflict warning).
3. Enrichment: incoming row HAS a kickoff time, exactly one stored match for
   the same (league, teams, date) has kickoff_utc NULL -> update that match's
   kickoff in place. No duplicate, no migration ever needed for better data.
4. Reverse: incoming row has NO time but a timed match exists for the same
   pairing/date -> duplicate (a coarser copy of known data).
5. Same-file/date-only double-header with different scores -> rejected as a
   conflict needing manual resolution or a source ID. Loud, never silent.

Generic odds backfill: every branch above that concludes "this row matches
an existing match" (1, 2, 3, and 4 when unambiguous) runs the row's odds
through ``_reconcile_odds`` — any quote the mapping profile derives from
this row that the match doesn't already have gets inserted (e.g. because the
profile gained columns since the match was first imported), an
already-stored identical quote is skipped, and a same-identity quote with a
DIFFERENT value is a loud warning, never a silent overwrite. This makes
extending a mapping profile (a new market, a new bookmaker, a new phase like
closing odds) apply retroactively to already-imported matches just by
re-running the same file, with no separate backfill tooling needed.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from footpred.domain.entities import (
    ImportRecord,
    Match,
    MatchSource,
    MatchStatus,
    OddsQuote,
    make_dedupe_key,
)
from footpred.domain.ports import UnitOfWork
from footpred.ingest.mapping import MappingProfile
from footpred.ingest.resolution import LeagueResolver, TeamResolver
from footpred.ingest.validation import ParsedRow, RowError, validate_row


@dataclass
class ImportReport:
    filename: str
    profile_name: str
    rows_total: int = 0
    rows_imported: int = 0
    rows_duplicate: int = 0
    rows_enriched: int = 0
    rows_rejected: int = 0
    odds_quotes_stored: int = 0
    odds_quotes_backfilled: int = 0
    rejections: List[dict] = field(default_factory=list)   # {row, reason}
    warnings: List[dict] = field(default_factory=list)     # {row, message}
    resolutions: List[dict] = field(default_factory=list)  # non-exact team decisions

    def add_rejection(self, row: int, reason: str) -> None:
        self.rows_rejected += 1
        self.rejections.append({"row": row, "reason": reason})

    def add_warning(self, row: int, message: str) -> None:
        self.warnings.append({"row": row, "message": message})

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)


class ImportPipeline:
    def __init__(self, uow: UnitOfWork, profile: MappingProfile):
        self._uow = uow
        self._profile = profile
        self._tz = ZoneInfo(profile.timezone)
        self._teams = TeamResolver(uow, source=profile.source_name)
        self._leagues = LeagueResolver(uow, profile)

    def run(self, df: pd.DataFrame, filename: str) -> ImportReport:
        report = ImportReport(filename=filename, profile_name=self._profile.name)
        report.rows_total = len(df)

        import_record = self._uow.imports.add(ImportRecord(
            id=None, filename=filename, profile_name=self._profile.name,
            rows_total=len(df), rows_imported=0, rows_duplicate=0,
            rows_enriched=0, rows_rejected=0, report_json="",
        ))

        for idx, row in df.iterrows():
            parsed = validate_row(row, int(idx), self._profile)
            if isinstance(parsed, RowError):
                report.add_rejection(parsed.row_index, parsed.reason)
                continue
            for w in parsed.warnings:
                report.add_warning(parsed.row_index, w)
            self._process(parsed, report, import_record.id)

        # persist final counters + full report on the import row
        import_record.rows_imported = report.rows_imported
        import_record.rows_duplicate = report.rows_duplicate
        import_record.rows_enriched = report.rows_enriched
        import_record.rows_rejected = report.rows_rejected
        import_record.report_json = report.to_json()
        return report

    # ------------------------------------------------------------------ #

    def _process(self, p: ParsedRow, report: ImportReport, import_id: Optional[int]) -> None:
        league = self._leagues.resolve(p.league_raw)
        if league is None:
            report.add_rejection(
                p.row_index,
                f"no league code (column {self._profile.league_col!r} missing or "
                "empty) and profile has no fixed league",
            )
            return

        home = self._teams.resolve(p.home_raw)
        away = self._teams.resolve(p.away_raw)
        for res in (home, away):
            if res.kind in ("fuzzy", "created"):
                entry = {"row": p.row_index, "raw": res.raw, "action": res.kind,
                         "matched_key": res.matched_key, "confidence": res.confidence}
                if entry not in report.resolutions:
                    report.resolutions.append(entry)
        if home.team_id == away.team_id:
            report.add_rejection(
                p.row_index,
                f"home and away resolved to the same team ({p.home_raw!r} / {p.away_raw!r})",
            )
            return

        kickoff_utc = self._to_utc(p)
        key = make_dedupe_key(league.id, home.team_id, away.team_id, p.match_date, kickoff_utc)

        # 1. external ID beats everything
        if p.external_id is not None:
            hit = self._uow.match_sources.get(self._profile.source_name, p.external_id)
            if hit is not None:
                report.rows_duplicate += 1
                self._reconcile_odds(hit.match_id, p, report)
                return

        # 2. exact natural-key hit
        existing = self._uow.matches.get_by_dedupe_key(key)
        if existing is not None:
            if (existing.ft_home, existing.ft_away) != (p.ft_home, p.ft_away):
                report.add_rejection(
                    p.row_index,
                    "conflict: same teams/date"
                    + ("" if kickoff_utc is None else "/time")
                    + f" but different score ({existing.ft_home}-{existing.ft_away} vs "
                    f"{p.ft_home}-{p.ft_away}); needs kickoff time or source ID",
                )
            else:
                report.rows_duplicate += 1
                self._reconcile_odds(existing.id, p, report)  # type: ignore[arg-type]
            return

        siblings = self._uow.matches.find_by_pairing_date(
            league.id, home.team_id, away.team_id, p.match_date  # type: ignore[arg-type]
        )
        # 3. enrichment: we now know the kickoff time of a date-only match
        if kickoff_utc is not None:
            dateonly = [m for m in siblings if m.kickoff_utc is None]
            if len(dateonly) == 1 and not [m for m in siblings if m.kickoff_utc is not None]:
                m = dateonly[0]
                m.kickoff_utc = kickoff_utc
                m.dedupe_key = key
                self._uow.matches.update(m)
                report.rows_enriched += 1
                report.add_warning(p.row_index,
                                   "existing date-only match enriched with kickoff time")
                self._maybe_add_source(m.id, p)
                self._reconcile_odds(m.id, p, report)  # type: ignore[arg-type]
                return
        # 4. coarser copy of an already-timed match
        else:
            if siblings:
                report.rows_duplicate += 1
                if len(siblings) == 1:
                    # unambiguous — exactly one existing match for this
                    # pairing/date. With >1 sibling there's no reliable way
                    # to tell which one this coarser row belongs to, so odds
                    # are left alone rather than guessed at.
                    self._reconcile_odds(siblings[0].id, p, report)  # type: ignore[arg-type]
                return

        # 5. genuinely new match
        match = self._uow.matches.add(Match(
            id=None, league_id=league.id, home_team_id=home.team_id,  # type: ignore[arg-type]
            away_team_id=away.team_id, match_date=p.match_date,
            kickoff_utc=kickoff_utc, ht_home=p.ht_home, ht_away=p.ht_away,
            ft_home=p.ft_home, ft_away=p.ft_away,
            status=MatchStatus.COMPLETED, import_id=import_id, dedupe_key=key,
        ))
        self._maybe_add_source(match.id, p)
        quotes = [OddsQuote(id=None, match_id=match.id, bookmaker=o.bookmaker,  # type: ignore[arg-type]
                            market=o.market, selection=o.selection,
                            decimal_odds=o.decimal_odds, line=o.line,
                            price_point=o.price_point, recorded_at=None)
                  for o in p.odds]
        self._uow.odds.add_many(quotes)
        report.odds_quotes_stored += len(quotes)
        report.rows_imported += 1

    def _reconcile_odds(self, match_id: int, p: ParsedRow, report: ImportReport) -> None:
        """Generic odds backfill (used by every "this row matches an
        existing match" branch): insert any odds this row's mapping produces
        that the match doesn't already have -- e.g. because the mapping
        profile gained columns (Asian Handicap, closing lines, ...) since
        the match was first imported. An identity match with the SAME value
        is skipped (already correctly stored); an identity match with a
        DIFFERENT value is a loud conflict, never a silent overwrite."""
        if not p.odds:
            return
        existing = self._uow.odds.existing_odds_for_match(match_id)
        new_quotes: List[OddsQuote] = []
        for o in p.odds:
            key = (o.bookmaker, o.market, o.selection, o.line, o.price_point)
            stored = existing.get(key)
            if stored is None:
                new_quotes.append(OddsQuote(
                    id=None, match_id=match_id, bookmaker=o.bookmaker, market=o.market,
                    selection=o.selection, decimal_odds=o.decimal_odds,
                    line=o.line, price_point=o.price_point, recorded_at=None,
                ))
            elif not math.isclose(stored, o.decimal_odds, abs_tol=1e-9):
                phase = "" if o.price_point is None else f"/{o.price_point}"
                line = "" if o.line is None else f"@{o.line}"
                report.add_warning(
                    p.row_index,
                    f"odds conflict for match {match_id} "
                    f"({o.bookmaker}/{o.market}/{o.selection}{line}{phase}): "
                    f"stored {stored} vs incoming {o.decimal_odds}; kept stored value",
                )
            # else: identical value already stored — nothing to do
        if new_quotes:
            self._uow.odds.add_many(new_quotes)
            report.odds_quotes_backfilled += len(new_quotes)

    def _maybe_add_source(self, match_id: Optional[int], p: ParsedRow) -> None:
        if p.external_id is not None and match_id is not None:
            if self._uow.match_sources.get(self._profile.source_name, p.external_id) is None:
                self._uow.match_sources.add(MatchSource(
                    id=None, match_id=match_id,
                    source=self._profile.source_name, external_id=p.external_id,
                ))

    def _to_utc(self, p: ParsedRow) -> Optional[datetime]:
        """Combine date + naive local time (profile tz, default Europe/Berlin)
        into a UTC instant. Date-only rows keep kickoff_utc = None."""
        if p.kickoff_time is None:
            return None
        local = datetime.combine(p.match_date, p.kickoff_time, tzinfo=self._tz)
        return local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
