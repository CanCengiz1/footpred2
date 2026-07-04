# Roadmap

Future-work items that are deliberately **not implemented yet** — design intent
and rationale only, so they aren't lost between sprints. Nothing in this file
should be treated as approved for implementation; each item still needs its
own explicit go-ahead when picked up.

## Paused feature registry

**Status: proposed, not implemented.**

**Motivation:** Sprint 4's "Team DNA" research line paused two feature
families (team-specific home/away split, halftime resilience) after both
failed pre-registered Stage 0 existence tests on the current single-season
dataset (1,312 matches, E0+E1+SP1, 2024-25 only) — not because the ideas were
bad, but because the dataset doesn't yet have enough history per team to
tell signal from noise. That evidence is a property of the *data*, not the
*feature*, so it will change as more seasons are imported. Right now that
re-evaluation is manual and depends on someone remembering these families
exist — this item replaces that with a tracked, reportable mechanism.

**Design:**

1. **Paused feature registry.** A structured record (one entry per paused
   family) capturing: family name, date paused, one-line reason, a pointer
   to the analysis/decision behind it, the retest thresholds it needs (see
   below), and its current status (`paused` / `eligible_for_retest` /
   `retesting` / `rejected_again` / `adopted`). Format TBD at implementation
   time (could be a YAML/JSON file under version control, or a DB table —
   a flat file is probably enough given the expected volume of entries).

2. **Retest thresholds per family.** Not one global threshold — different
   families need different data shapes:
   - **Minimum seasons.** Draft default: 3 seasons of history before
     retesting any team-specific behavioural family. Rationale: a single
     season forces within-season half-split testing (as used for both
     paused families), which is itself a compromise; multiple full seasons
     let Stage 0 use season-level (not half-season) splits, and roughly
     triples the per-team sample.
   - **Minimum matches per team (venue-specific, where relevant).** Draft
     default: >= 50 matches/team at the relevant venue. Current data gives
     ~19-23 home (or away) matches/team/season — this threshold is set at
     roughly 2.5x that, to meaningfully shrink sampling-noise std, not just
     nominally add more rows.
   - **Minimum event counts (for conditional/rare-event families only, e.g.
     comeback tendency, HT/FT rare-outcome families).** Draft default: >= 40
     qualifying events/team. [[sprint4_team_dna_proposal]]'s own sample-size
     math found ~10-13 trailing-at-HT situations/team/season producing a
     ~+/-19pp confidence interval on the resulting rate — 40+ events is the
     rough order of magnitude needed to tighten that to something usable.
   - These are initial draft numbers for scoping purposes, not final —
     revisit them against the specific family's statistical design when this
     is actually built.

3. **Post-import eligibility report.** After each data import, compute
   current data-volume metrics (seasons available, matches/team, relevant
   event counts) and compare against every paused family's thresholds.
   Report which families just became eligible for Stage 0 retesting (if
   any) — a notification/summary, not an action.

4. **Human-in-the-loop only, and eligibility is a two-stage gate — never a
   shortcut to implementation.** Crossing a data-volume threshold does not
   mean a feature is good; it only means the *original* Stage 0 test can be
   meaningfully rerun. The flow is strictly:
   - Threshold crossed -> system recommends a Stage 0 **retest** ("family X
     is now eligible for Stage 0 retest given N seasons of data — retest?").
     Requires explicit confirmation to even run the retest.
   - Stage 0 retest passes -> feature returns to the **implementation
     backlog** (Stage 1/2 candidate) — it is not built automatically.
     Building it still needs its own separate explicit go-ahead, same as any
     other feature-engineering decision (see `feature_engineering_discipline`
     in memory).
   - Stage 0 retest fails -> family stays paused; thresholds are not
     loosened or re-tried immediately just because a retest was disappointing.
   At no point does crossing a threshold, or a passing Stage 0 result, cause
   code to be written without a human explicitly asking for it.

**Currently paused families this would track:** team-specific home/away
split, halftime resilience (continuous reformulation). **Both remain paused
after the M1 retest** (see Data Expansion phase below) — the registry
mechanism itself is still unbuilt (this section is design only), but the
retest it would have triggered was run manually and documented there.

## Data Expansion phase

**Status: in progress — M1 executed, M2-M4 not started.** Sprint 4 concluded
that the bottleneck for team-behavioural features is data volume, not feature
design (see "Sprint 4" below). This phase grows the database so the
paused-feature registry above has something to actually evaluate against.

**Governing rule: depth before breadth, and never skip football-data.co.uk
for a new provider early.** Fully exhaust football-data.co.uk's available
historical seasons — for the leagues already in the DB, and any further
leagues it covers — before considering any other data provider. A new
provider is only justified once that source is genuinely exhausted, or for
data football-data.co.uk structurally does not have (see Phase 5).

1. **Phase 1 — Depth on the existing 3 leagues (highest priority). DONE
   (M1, 2026-07-04).** Imported 2020-21 through 2023-24 for E0/E1/SP1 (12
   files, existing importer, zero rejections, zero fuzzy-match aliases) —
   DB grew from 1,312 to 6,560 matches, 1 to 5 seasons/league. See "M1
   results" below.
2. **Phase 2 — Per-team threshold verification (checkpoint, not an import
   step). DONE (M1).** Per-team venue-match counts checked, not just league
   averages: median team has 69-76 matches/venue (comfortably over the
   50 minimum); 29 of 94 team-league rows fall short (teams promoted/
   relegated partway through the window, as expected) — not a data-quality
   issue, just less depth for those specific teams.
3. **Phase 3 — Extend to a 4th season for the event-conditioned bucket.**
   Rare-event families (comeback tendency, lead-protection) need ~40
   qualifying events/team; 3 seasons gives roughly 30-39 trailing-at-HT
   situations/team, just under threshold. **Threshold technically crossed by
   M1's 5 seasons (~50-65 events/team)**, but this bucket was never
   registered as a paused family and wasn't tested in M1 — M1 stayed scoped
   to retesting only the two already-paused families with their unchanged
   original protocols. Running a first-ever Stage 0 for this bucket is a
   separate, not-yet-taken decision.
4. **Phase 4 — Breadth: additional leagues, still football-data.co.uk.**
   Add further leagues the same provider covers (e.g. other English
   divisions, other top-tier European leagues), same importer, no code
   changes. Raises pooled Stage 0 power and opens new candidates, but does
   not by itself deepen any single paused family's own per-team history.
5. **Phase 5 — New data provider (deferred, gated).** Only after Phases 1-4
   have exhausted what football-data.co.uk offers. The one family already
   flagged as needing this: late-goal tendency (NOT_COMPUTABLE per
   [[sprint4_team_dna_proposal]] — needs goal-minute event data, which
   football-data.co.uk does not carry). Requires both a new provider and an
   ingest schema change — a distinct decision from "import more of the same,"
   not to be conflated with ordinary volume growth.

**Verification note:** the season counts and thresholds above are planning
estimates; before executing Phase 1, confirm which season files
football-data.co.uk actually has available for E0/E1/SP1 rather than
assuming coverage.

### M1 results (2026-07-04): both paused families remain paused

Imported 2020-21 -> 2023-24 (E0/E1/SP1, football-data.co.uk, existing
importer, 0 rejections, 0 fuzzy-match aliases). Reran the **original,
unmodified** Stage 0 scripts for both registered families against the
5-season dataset, same pre-registered success/rejection criteria as the
single-season baseline.

**Home/away split** (primary metric: points, pooled, league fixed effects):

| | baseline (1 season, n=64) | M1 (5 seasons, n=70) |
|---|---|---|
| home incr. R² / p / coef | 0.0002 / 0.881 / +0.041 | 0.0001 / 0.926 / -0.023 |
| away incr. R² / p / coef | 0.0080 / 0.431 / -0.200 | 0.0004 / 0.821 / -0.054 |

**Halftime resilience** (pooled, league fixed effects):

| | baseline (n=64) | M1 (n=70) |
|---|---|---|
| incr. R² / p / coef | 0.0211 / 0.264 / -0.158 | 0.0125 / 0.327 / -0.108 |

**Finding:** both families moved *further* from the pre-registered success
bar with 5x the data, not closer. If either effect were real-but-power-limited,
more data should have tightened the estimates toward some non-zero value —
instead effect sizes shrank and p-values grew. Sharpest example: at baseline,
SP1 alone showed the single largest per-league resilience hit (incr.
R²=0.108, the number that made resilience look borderline-promising); at M1,
SP1's incr. R² collapsed to 0.0026 — a single-season fluke evaporating
exactly as more data arrived. One secondary metric (venue away-GA) crossed
p<0.10 for the first time (p=0.080), but it wasn't the pre-registered primary
metric, and its coefficient sign is still the same mean-reversion direction
seen everywhere else, not the persistence direction the hypothesis needs —
read as one of 18 secondary tests crossing by chance, not a promotion signal.

**Decision: neither family returns to the implementation backlog.** Per the
unchanged pre-registered criteria, both fail more decisively than at
baseline — evidence trending toward the null with more data, not away from
it.

## Sprint 4 (closed): evidence-driven feature research framework

**Status: closed.** Sprint 4 intentionally shipped no production feature
code. Its deliverable was a research framework:

- The Stage 0 methodology itself, including the lesson that a Stage 0 test
  must target the exact predictive claim a feature depends on, not a proxy
  claim that merely sounds related (see `feature_engineering_discipline` in
  memory).
- Two feature families tested and correctly paused rather than built on
  intuition: team-specific home/away split and halftime resilience — both
  failed independently-designed, pre-registered Stage 0 tests on the current
  single-season dataset.
- The paused-feature registry (above): a mechanism so paused families are
  revisited as evidence changes instead of forgotten.
- Retest thresholds (minimum seasons, minimum matches/team, minimum event
  counts) defining exactly when a retest is warranted.
- Formalization of the eligibility -> retest -> (pass) -> backlog gate,
  never eligibility -> implementation directly.

See project memory (`sprint4_team_dna_proposal`, `sprint4a_resolution`,
`sprint4b_resolution`, `sprint4_team_dna_paused`, `sprint4_closed`) for the
full analysis trail. Next: Data Expansion phase, above.
