from pathlib import Path

import pandas as pd

from footpred.domain.entities import Bookmaker
from footpred.infra.memory import InMemoryUnitOfWork
from footpred.ingest.mapping import FOOTBALL_DATA_CO_UK, MappingProfile, OddsColumn
from footpred.ingest.pipeline import ImportPipeline
from footpred.ingest.readers import read_table
from footpred.services.import_service import ImportService

SAMPLE = Path(__file__).parent / "data" / "sample_fd.csv"


def load_sample() -> pd.DataFrame:
    return read_table(SAMPLE, "sample_fd.csv")


def test_end_to_end_import_counts():
    uow = InMemoryUnitOfWork()
    report = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(load_sample(), "sample_fd.csv")

    # 9 rows: 6 valid distinct, 1 missing-team reject, 1 missing-FT reject,
    # 1 exact duplicate of row 0
    assert report.rows_total == 9
    assert report.rows_imported == 6
    assert report.rows_duplicate == 1
    assert report.rows_rejected == 2
    assert uow.matches.count() == 6

    # warnings: partial HT (Newcastle), impossible HT (Brentford), bad odds (Villa)
    msgs = " | ".join(w["message"] for w in report.warnings)
    assert "half-time" in msgs and "impossible" in msgs and "< 1.01" in msgs

    # long-format odds landed, both bookmakers present
    books = {q.bookmaker for q in uow.odds.items}
    assert books == {Bookmaker.BET365.value, Bookmaker.MARKET_AVG.value}
    assert report.odds_quotes_stored == uow.odds.count() > 0

    # two leagues resolved from Div codes
    names = {l.name for l in uow.leagues.all()}
    assert names == {"Premier League", "Bundesliga"}

    # unknown odds timing stored as None
    assert all(q.recorded_at is None for q in uow.odds.items)

    # UTC conversion: 13:30 Europe/Berlin in August (CEST) == 11:30 UTC
    timed = [m for m in _all_matches(uow) if m.kickoff_utc is not None]
    arsenal = min(timed, key=lambda m: m.kickoff_utc)
    assert (arsenal.kickoff_utc.hour, arsenal.kickoff_utc.minute) == (11, 30)

    # date-only row (Newcastle) has NULL kickoff, not fake midnight
    dateonly = [m for m in _all_matches(uow) if m.kickoff_utc is None]
    assert len(dateonly) == 1


def _all_matches(uow):
    return uow.matches._items  # test-only peek


def test_reimport_is_idempotent():
    uow = InMemoryUnitOfWork()
    ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(load_sample(), "a.csv")
    n = uow.matches.count()
    report2 = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(load_sample(), "a.csv")
    assert report2.rows_imported == 0
    assert report2.rows_duplicate == 7  # 6 matches + in-file duplicate row
    assert uow.matches.count() == n


def test_enrichment_dateonly_match_gains_kickoff_without_duplicate():
    uow = InMemoryUnitOfWork()
    pipe = ImportPipeline(uow, FOOTBALL_DATA_CO_UK)
    base = {"Div": "E0", "Date": "17/08/2025", "HomeTeam": "Newcastle",
            "AwayTeam": "Fulham", "FTHG": 1, "FTAG": 1, "HTHG": 0, "HTAG": 0}
    pipe.run(pd.DataFrame([{**base, "Time": None}]), "dateonly.csv")
    assert uow.matches.count() == 1
    assert _all_matches(uow)[0].kickoff_utc is None

    report = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(
        pd.DataFrame([{**base, "Time": "14:00"}]), "timed.csv")
    assert report.rows_enriched == 1
    assert report.rows_imported == 0
    assert uow.matches.count() == 1
    assert _all_matches(uow)[0].kickoff_utc is not None  # enriched in place

    # reverse direction: a date-only copy of the now-timed match is a duplicate
    report3 = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(
        pd.DataFrame([{**base, "Time": None}]), "dateonly2.csv")
    assert report3.rows_duplicate == 1
    assert uow.matches.count() == 1


def test_same_day_double_header_without_time_conflicts_loudly():
    uow = InMemoryUnitOfWork()
    rows = [
        {"Div": "E0", "Date": "17/08/2025", "Time": None, "HomeTeam": "A",
         "AwayTeam": "B", "FTHG": 1, "FTAG": 0},
        {"Div": "E0", "Date": "17/08/2025", "Time": None, "HomeTeam": "A",
         "AwayTeam": "B", "FTHG": 2, "FTAG": 2},  # different score, no time
    ]
    report = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame(rows), "x.csv")
    assert report.rows_imported == 1
    assert report.rows_rejected == 1
    assert "conflict" in report.rejections[0]["reason"]

    # with kickoff times, both legs store fine
    uow2 = InMemoryUnitOfWork()
    for r, t in zip(rows, ("12:00", "18:00")):
        r["Time"] = t
    report2 = ImportPipeline(uow2, FOOTBALL_DATA_CO_UK).run(pd.DataFrame(rows), "y.csv")
    assert report2.rows_imported == 2


def _ext_id_profile() -> MappingProfile:
    return MappingProfile(
        name="ext", source_name="ext-src", date_col="d", home_col="h", away_col="a",
        fthg_col="fh", ftag_col="fa", dayfirst=True, external_id_col="mid",
        fixed_league=("lg", "League", None),
        odds_columns={"o1": OddsColumn("bet365", "1x2", "home")},
    )


def test_external_id_beats_natural_key():
    uow = InMemoryUnitOfWork()
    p = _ext_id_profile()
    row = {"d": "01/09/2025", "h": "X", "a": "Y", "fh": 1, "fa": 0,
           "mid": "M-1", "o1": 2.0}
    ImportPipeline(uow, p).run(pd.DataFrame([row]), "f1.csv")
    # same external ID again -> duplicate even from another file
    report = ImportPipeline(uow, p).run(pd.DataFrame([row]), "f2.csv")
    assert report.rows_duplicate == 1
    assert uow.matches.count() == 1
    assert uow.match_sources.get("ext-src", "M-1") is not None


def test_import_service_facade_and_summary():
    uow = InMemoryUnitOfWork()
    service = ImportService(lambda: uow)
    preview, df = service.preview(SAMPLE, "sample_fd.csv")
    assert preview.auto_apply and preview.detected_profile.name == "football-data.co.uk"

    report = service.import_dataframe(df, "sample_fd.csv", preview.detected_profile)
    assert report.rows_imported == 6
    assert uow.committed == 1  # one file == one transaction

    summary = service.database_summary()
    assert summary["matches"] == 6
    assert summary["imports"][0]["imported"] == 6
    league_names = {e["league"] for e in summary["leagues"]}
    assert "Premier League" in league_names


def test_bom_csv_regression(tmp_path=None):
    """Real football-data.co.uk CSVs carry a UTF-8 BOM; the first column
    must resolve as 'Div', not '\\ufeffDiv', and rows must import."""
    import io
    from footpred.ingest.mapping import detect_profile

    raw = SAMPLE.read_bytes()
    bom_buffer = io.BytesIO(b"\xef\xbb\xbf" + raw)
    df = read_table(bom_buffer, "bom_sample.csv")
    assert df.columns[0] == "Div"

    profile, score = detect_profile(df.columns)
    assert score >= 0.7 and not profile.missing_core_columns(df.columns)

    uow = InMemoryUnitOfWork()
    report = ImportPipeline(uow, profile).run(df, "bom_sample.csv")
    assert report.rows_imported == 6
    assert not any("no league code" in r["reason"] for r in report.rejections)


def test_missing_core_columns_diagnostic():
    cols = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]  # no Div
    assert FOOTBALL_DATA_CO_UK.missing_core_columns(cols) == ["Div"]
    assert FOOTBALL_DATA_CO_UK.missing_core_columns(cols + ["Div"]) == []


# --------------------------- generic odds backfill ------------------------- #

_NARROW_ROW = {
    "Div": "E0", "Date": "17/08/2025", "HomeTeam": "Newcastle", "AwayTeam": "Fulham",
    "FTHG": 1, "FTAG": 0, "B365H": 1.9, "B365D": 3.4, "B365A": 4.2,
}


def test_backfill_inserts_new_columns_without_duplicating_existing_ones():
    uow = InMemoryUnitOfWork()
    ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([_NARROW_ROW]), "narrow.csv")
    assert uow.odds.count() == 3  # B365H/D/A only

    extended = {**_NARROW_ROW, "AHh": -0.5, "B365AHH": 1.95, "B365AHA": 1.87,
                "B365CH": 1.85, "B365CD": 3.5, "B365CA": 4.4}
    report = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([extended]), "extended.csv")

    assert report.rows_duplicate == 1
    assert report.rows_imported == 0
    assert report.odds_quotes_backfilled == 5  # 2 AH (opening) + 3 1x2 closing
    assert uow.matches.count() == 1  # still one match, not a second one
    assert uow.odds.count() == 3 + 5

    ah_quotes = [q for q in uow.odds.items if q.market == "ah"]
    assert len(ah_quotes) == 2
    assert all(q.line == -0.5 and q.price_point == "opening" for q in ah_quotes)
    closing_1x2 = [q for q in uow.odds.items if q.market == "1x2" and q.price_point == "closing"]
    assert len(closing_1x2) == 3
    assert all(q.line is None for q in closing_1x2)

    # original opening 1x2 quotes are untouched, not duplicated
    opening_1x2 = [q for q in uow.odds.items if q.market == "1x2" and q.price_point is None]
    assert len(opening_1x2) == 3


def test_backfill_is_idempotent_on_a_third_identical_pass():
    uow = InMemoryUnitOfWork()
    extended = {**_NARROW_ROW, "AHh": -0.5, "B365AHH": 1.95, "B365AHA": 1.87}
    ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([_NARROW_ROW]), "narrow.csv")
    ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([extended]), "extended.csv")
    n = uow.odds.count()

    report3 = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([extended]), "extended2.csv")
    assert report3.odds_quotes_backfilled == 0
    assert uow.odds.count() == n


def test_backfill_conflict_is_a_loud_warning_not_a_silent_overwrite():
    uow = InMemoryUnitOfWork()
    ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([_NARROW_ROW]), "narrow.csv")

    conflicting = {**_NARROW_ROW, "B365H": 2.5}  # same identity, different price
    report = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([conflicting]), "conflict.csv")

    assert report.odds_quotes_backfilled == 0
    assert uow.odds.count() == 3  # nothing added
    b365h = next(q for q in uow.odds.items if q.bookmaker == "bet365" and q.selection == "home")
    assert b365h.decimal_odds == 1.9  # stored value kept, not overwritten by 2.5
    assert any("conflict" in w["message"] for w in report.warnings)


def test_backfill_applies_on_kickoff_enrichment_branch():
    uow = InMemoryUnitOfWork()
    dateonly = {**_NARROW_ROW, "Time": None}
    ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([dateonly]), "dateonly.csv")
    assert uow.odds.count() == 3

    timed_and_extended = {**_NARROW_ROW, "Time": "14:00", "AHh": -0.5,
                           "B365AHH": 1.95, "B365AHA": 1.87}
    report = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(
        pd.DataFrame([timed_and_extended]), "timed_extended.csv")

    assert report.rows_enriched == 1
    assert report.odds_quotes_backfilled == 2
    assert uow.matches.count() == 1
    assert uow.odds.count() == 5


def test_backfill_applies_on_reverse_coarser_duplicate_branch():
    uow = InMemoryUnitOfWork()
    timed = {**_NARROW_ROW, "Time": "14:00"}
    ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([timed]), "timed.csv")
    assert uow.odds.count() == 3

    coarser_extended = {**_NARROW_ROW, "Time": None, "AHh": -0.5,
                         "B365AHH": 1.95, "B365AHA": 1.87}
    report = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(
        pd.DataFrame([coarser_extended]), "coarser.csv")

    assert report.rows_duplicate == 1
    assert report.odds_quotes_backfilled == 2
    assert uow.matches.count() == 1
    assert uow.odds.count() == 5


def test_backfill_applies_on_external_id_duplicate_branch():
    ext_profile = _ext_id_profile()
    uow = InMemoryUnitOfWork()
    row1 = {"d": "01/09/2025", "h": "X", "a": "Y", "fh": 1, "fa": 0, "mid": "M-1", "o1": 2.0}
    ImportPipeline(uow, ext_profile).run(pd.DataFrame([row1]), "f1.csv")
    assert uow.odds.count() == 1

    ext_profile_with_ah = MappingProfile(
        name="ext", source_name="ext-src", date_col="d", home_col="h", away_col="a",
        fthg_col="fh", ftag_col="fa", dayfirst=True, external_id_col="mid",
        fixed_league=("lg", "League", None),
        odds_columns={
            "o1": OddsColumn("bet365", "1x2", "home"),
            "o2": OddsColumn("bet365", "ah", "home", line_col="lin", price_point="opening"),
        },
    )
    row2 = {**row1, "o2": 1.95, "lin": -0.5}
    report = ImportPipeline(uow, ext_profile_with_ah).run(pd.DataFrame([row2]), "f2.csv")

    assert report.rows_duplicate == 1
    assert report.odds_quotes_backfilled == 1
    assert uow.matches.count() == 1
    assert uow.odds.count() == 2


def test_ambiguous_multi_sibling_reverse_duplicate_skips_backfill():
    """With more than one sibling for the pairing/date, there's no reliable
    way to tell which one a coarser (no-time) row belongs to -- odds must be
    left alone rather than guessed at."""
    uow = InMemoryUnitOfWork()
    row_a = {**_NARROW_ROW, "Time": "12:00"}
    row_b = {**_NARROW_ROW, "Time": "18:00", "FTHG": 2, "FTAG": 2}
    ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([row_a, row_b]), "two.csv")
    assert uow.matches.count() == 2
    n = uow.odds.count()

    coarser = {**_NARROW_ROW, "Time": None, "AHh": -0.5, "B365AHH": 1.95, "B365AHA": 1.87}
    # ambiguous vs. row_a's score -> lands as a same-teams/date conflict or
    # duplicate depending on score match; use row_a's exact score so it's a
    # clean duplicate match against >1 sibling
    report = ImportPipeline(uow, FOOTBALL_DATA_CO_UK).run(pd.DataFrame([coarser]), "coarser.csv")
    assert report.odds_quotes_backfilled == 0
    assert uow.odds.count() == n


def test_overround_check_does_not_mix_opening_and_closing_quotes():
    """A row with both opening and closing 1x2 odds must not have its
    overround sanity check pool all 6 quotes into one trio."""
    row = {**_NARROW_ROW, "B365CH": 1.85, "B365CD": 3.5, "B365CA": 4.4}
    from footpred.ingest.validation import validate_row
    parsed = validate_row(pd.Series(row), 0, FOOTBALL_DATA_CO_UK)
    assert not any("outside [1.00, 1.25]" in w for w in parsed.warnings)
    book_phases = {(o.bookmaker, o.price_point) for o in parsed.odds if o.market == "1x2"}
    assert book_phases == {("bet365", None), ("bet365", "closing")}


def test_aggregate_era_asian_handicap_line_and_bookmaker():
    """2015/16-2018/19-style files: only a pooled market-average AH price
    exists (BbAvAHH/BbAvAHA), sharing one line column (BbAHh)."""
    row = {**_NARROW_ROW, "BbAHh": -0.5, "BbAvAHH": 1.93, "BbAvAHA": 1.98}
    from footpred.ingest.validation import validate_row
    parsed = validate_row(pd.Series(row), 0, FOOTBALL_DATA_CO_UK)
    ah = [o for o in parsed.odds if o.market == "ah"]
    assert len(ah) == 2
    assert all(o.bookmaker == "market_avg" and o.line == -0.5 and o.price_point == "opening"
               for o in ah)
