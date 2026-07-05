# FootPred — Sprint 1: Skeleton + Ingestion

Local-first football prediction platform. Sprint 1 delivers the project
skeleton, the database layer, and a robust historical-data import pipeline
with flexible column mapping, entity resolution, validation, and an import
report UI. No ML yet (Sprint 2+).

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python scripts/init_db.py                            # runs Alembic migrations
streamlit run src/footpred/ui/streamlit_app/app.py
```

DB location: `footpred.db` (SQLite) by default; override with the
`FOOTPRED_DB` env var (e.g. a PostgreSQL URL later — nothing else changes).

## Tests

```bash
pytest                      # full suite
python scripts/run_tests.py # zero-dependency fallback runner
```

## Using the importer

1. Upload a CSV/Excel file. football-data.co.uk layouts are auto-detected.
2. Other layouts: drop a JSON mapping profile into
   `configs/mapping_profiles/` (see `example_custom_profile.json`) and pick
   it in the UI. No code changes needed for new sources.
3. Review the import report: imported / duplicates / enriched / rejected,
   warnings, and the team-resolution log (fuzzy matches and new teams).
4. Re-importing the same file is safe (idempotent): everything is reported
   as duplicates.

## Key design decisions

- **Identity vs. timing separated.** `matches.match_date` is always known;
  `matches.kickoff_utc` is nullable and filled when a source provides it.
  If a better source later supplies the kickoff time of a date-only match,
  the pipeline *enriches* the existing row instead of duplicating it.
- **External IDs first-class.** `match_sources(source, external_id)` maps
  provider IDs to matches, so future API integrations get perfect dedupe.
- **Conflicts are loud.** Two date-only rows, same teams/date, different
  scores → the second is rejected as a conflict, never silently merged.
- **Ports & adapters.** `domain/ports.py` defines repository protocols;
  `infra/db` (SQLAlchemy) and `infra/memory` (tests) implement them. The
  ingest pipeline, services and UI never import SQLAlchemy.
- **Odds in long format** (`bookmaker, market, selection, price`); unknown
  odds timing → `recorded_at = NULL`. New markets need no schema change.
- **Entity resolution is conservative** (fuzzy threshold 0.92) and every
  non-exact decision is persisted to `team_aliases` and surfaced in the
  report — false merges corrupt silently, false splits are fixable.
- **Timezone:** naive dates/times are interpreted in the profile's timezone
  (default Europe/Berlin) and stored as UTC.

## Layout

```
src/footpred/domain     entities + ports (pure, zero deps)
src/footpred/ingest     readers, mapping, validation, resolution, pipeline
src/footpred/services   application facade (UI entry point)
src/footpred/infra      SQLAlchemy UoW + in-memory UoW
src/footpred/ui         Streamlit adapter (thin)
migrations/             Alembic migrations
configs/mapping_profiles/  user-defined JSON column mappings
tests/                  full suite runs without any database
```

## Sprint 2: odds math, datasets, market baseline, backtesting

- `footpred.ml.odds_math` — implied probabilities, overround, extensible
  de-vig registry (proportional / power / shin built in).
- `footpred.ml.features` — versioned, registry-based feature groups
  (`odds_core` v1.0: raw implied, overrounds, all de-vig methods,
  Bet365-vs-market divergence).
- `footpred.ml.datasets` — DatasetBuilder → versioned Parquet/CSV artifact
  + JSON manifest (schema_version, per-group versions, split config,
  content hash) under `data/datasets/`.
- `footpred.ml.splits` — FixedCutoffSplit, GroupFractionSplit (70/30 per
  league default), WalkForwardSplit (rolling & expanding) + leakage guard.
- `footpred.ml.backtest` — log loss / Brier / calibration+ECE, flat-stake
  simulator (value-threshold & bet-all), BacktestRunner over the stable
  Predictor protocol.
- `footpred.ml.baselines.MarketBaseline` — B0: de-vigged market
  probabilities as the prediction; the benchmark all models must beat.
- UI: **Evaluation** page (build dataset → run B0 → de-vig comparison,
  calibration, simulations).

## Sprint 4 (closed): evidence-driven feature research framework

Sprint 4 intentionally produced **no production feature code**. Its
deliverable was a research framework for evaluating future "Team DNA"
(team-behavioural) feature candidates before implementation effort goes
into them:

- **Stage 0 methodology** — a cheap existence test run on data already in
  hand before any leakage-safe pipeline code is written, refined mid-sprint
  to a rule that generalizes beyond this sprint: a Stage 0 test must target
  the exact predictive claim a feature depends on, not a proxy claim (e.g.
  population-level effect significance) that merely sounds related.
- **Two feature families tested and paused, not implemented** — team-specific
  home/away split and halftime resilience — both failed independently
  designed, pre-registered Stage 0 tests on the current single-season
  dataset (1,312 matches, E0+E1+SP1). The evidence points at data volume as
  the limiting factor, not the feature designs.
- **Paused-feature registry** (see `ROADMAP.md`) — tracks paused families and
  the retest thresholds (minimum seasons, matches/team, event counts) each
  one needs before a Stage 0 retest is warranted, so they're revisited as
  the database grows instead of forgotten.
- **A strict eligibility gate** — a threshold being crossed only ever
  triggers a recommendation to rerun Stage 0; a passing retest returns a
  feature to the implementation backlog, it never triggers implementation
  directly. See `ROADMAP.md` for the full gate definition.

Next phase: **Data Expansion** — grow the database (depth before breadth,
football-data.co.uk exhausted before any new provider) so the paused
registry above has real milestones to evaluate against. See `ROADMAP.md`.

## Canonical Prediction Engine (docs/VISION.md made runnable)

Turns the product vision into running code: one canonical FootPred
prediction per match, built as an evidence-tier-weighted blend of the
promoted baseline and any live findings, via logarithmic opinion pooling
(weighted sum in logit space, softmax-renormalized). Market-agnostic by
construction — every quantity is indexed by `MARKETS[market]["selections"]`,
so 1x2 today and btts/ou/htft later need no engine change.

- `footpred.ml.evidence` — the findings registry (`configs/findings_registry.json`)
  and the fixed, pre-registered tier weights (rejected/not_confirmed = 0,
  provisionally_promoted = 0.25, promoted = 1.0).
- `footpred.ml.models.coherence` — `compute_coherence_features`: the
  cross-market-coherence signal (see `docs/RESEARCH_RETROSPECTIVE.md`)
  reimplemented as reusable, tested code — it previously existed only as
  uncommitted analysis code, closing a reproducibility gap found while
  scoping this milestone.
- `footpred.ml.models.canonical.CanonicalPredictor` — the engine itself.
  `predict_proba(market, X)` (the canonical number) plugs into
  `BacktestRunner` unchanged; `explain(market, X)` returns the full audit
  record — baseline, canonical, and the internal promoted-only
  counterfactual that lets a provisionally-promoted finding's forward
  production performance be re-tested for independent replication without
  ever being shown to a user.
- `footpred.ml.predictions_log` — persists `explain()`'s output as a
  long-format artifact (`data/predictions/`, Parquet + manifest, same
  content-hash discipline as `datasets.py`) — one row per
  (match, role/finding, selection), so adding a market with a different
  outcome count never needs a schema change, mirroring the `odds` table's
  own long-format design.
- Today the registry holds exactly one finding (`coherence_1x2`,
  provisionally promoted, 1x2 only), so the canonical prediction is a small
  shrunk nudge on top of the de-vigged market baseline — B0 remains the
  anchor, per `docs/VISION.md`. Backtest/offline mode only; live-mode
  ingestion and the DB-backed predictions table are designed in
  `docs/VISION.md` but not built yet. 37 new tests (134/134 total).
