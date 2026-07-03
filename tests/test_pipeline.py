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
