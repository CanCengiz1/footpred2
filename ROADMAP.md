# Roadmap

Future-work items that are deliberately **not implemented yet** — design intent
and rationale only, so they aren't lost between sprints. Nothing in this file
should be treated as approved for implementation; each item still needs its
own explicit go-ahead when picked up.

**Scope note:** this file tracks future milestones and execution history only.
For accumulated research findings — falsified hypotheses, open questions, and
the methodology behind them — see
[`docs/RESEARCH_RETROSPECTIVE.md`](docs/RESEARCH_RETROSPECTIVE.md). Check that
document before proposing a new research direction; this one is not the place
to re-derive whether an idea has already been tested.

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

**Status: in progress — M1 and M2 executed, M3-M4 not started.** Sprint 4 concluded
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

### M2+ objective reframe and retest stopping rule (2026-07-04)

**From M2 onward, further data-volume growth is justified as dataset
expansion for future predictive modeling — not as continued search for
evidence supporting the two paused families.** M1 already produced a
decisive, pre-registered answer for both (above). Continuing to frame
further imports around "will these become significant yet" would be a
slow-motion form of optional stopping that undermines the pre-registration
discipline itself — M1 already surfaced one secondary metric crossing
p<0.10 by chance out of 18 tests run; more milestones and more metrics
without a stopping rule would only amplify that risk. M2's actual
justification is what it does independent of these two families: bigger
training data for Dixon-Coles refits, more powerful backtests, and better
walk-forward validation.

**Stopping rule for the two already-paused families (home/away split,
halftime resilience):**
- At M2, the same two original, unmodified Stage 0 scripts *may* be rerun
  once more as a passive confirmatory datapoint (near-zero cost, extends
  the trend line already documented above) — not as the reason M2 happens.
- **After M2, scheduled retesting of these two specific families stops,
  regardless of the M2 result.** There is no M3/M4 retest of these two
  planned.
- A reversal at M2 (unlikely given the direction observed at M1, but
  possible) is treated as a standalone, surprising finding warranting its
  own dedicated investigation — not automatic promotion to the
  implementation backlog, and not a reason to resume the retest cadence.

**Scope of the stopping rule:** it applies only to *scheduled milestone
retests of the current hypotheses* — i.e. rerunning the same Stage 0 test,
unchanged, purely because a new data-volume milestone was reached. It does
**not** block re-evaluation triggered by a material change in any of:
the underlying hypothesis, the feature definition, the available data
(e.g. event/xG data becoming available), the data source, or the
experimental methodology itself. Any such change is a **new research
question**, to be scoped and pre-registered on its own terms — not a
continuation of the current Stage 0 evaluation, and therefore not
something this stopping rule constrains.

**Event-conditioned bucket (comeback tendency, lead-protection) is exempt
from this stopping rule.** It has never had a first Stage 0 test — unlike
the two paused families, testing it is a first-time candidate evaluation,
not a repeated look. It already crossed its data-volume threshold at M1
(~50-65 qualifying events/team vs. the 40 minimum, see Phase 3 above) and
can be considered on its own merits whenever picked up, independent of
M2/M3 dataset-expansion planning.

### M2 results (2026-07-04)

**M2's real purpose: training-data expansion for future predictive
models — not another feature-validation milestone.** Per the reframe above,
M2 was executed to grow the dataset for future Dixon-Coles refits, backtest
power, and walk-forward validation. It was not run in search of evidence
for the two paused families; any Stage 0 output below is a side effect of
having more data, not the reason the import happened.

**Import.** Verified all 15 target files (2015-16 -> 2019-20, E0/E1/SP1)
were actually available (HTTP 200) and format-checked *before* importing,
per the plan. All passed. Imported cleanly: 6,560 matches added (E0 1,900 /
E1 2,760 / SP1 1,900), 0 rejected, 0 duplicates. **Total: 13,120 matches,
10 seasons/league (2015-16 -> 2024-25).** Cumulative rejections across every
import to date: 0.

**Entity resolution.** 87 total teams (up from 80 after M1), zero
low-confidence/fuzzy-match aliases in the entire DB. Spot-checked the four
known yo-yo teams (Bournemouth, Fulham, Norwich, Watford) — each resolves
to a single `team_id` with matches correctly split across E0/E1 by date, no
duplicate entities from promotion/relegation churn.

**Format differences encountered.** 2015-2017 files use 2-digit years
(`07/08/15`) vs. later files' 4-digit years — verified this parses to the
correct century through the actual pipeline date parser
(`pd.to_datetime(..., dayfirst=True)`) before importing, not assumed to
work. One source-data quality note (not a pipeline issue): `E1_1819.csv`
has 2 rows with missing HT scores — handled natively by the nullable
schema, simply excluded from HT-dependent analysis downstream. No importer
or schema changes were required, as expected.

**Final validation:** all of the above passed — clean import, verified
entity resolution, format differences understood and confirmed non-breaking
ahead of time rather than discovered after the fact.

**Passive Stage 0 rerun — final scheduled confirmatory retest only,** per
the stopping rule agreed before execution. Not a search for evidence; not
followed by any further scheduled retest of these two families regardless
of outcome.

*Home/away split* (primary metric: points, pooled, league fixed effects):

| | baseline (n=64) | M1 (n=70) | M2 (n=75) |
|---|---|---|---|
| home incr. R² / p / coef | 0.0002/0.881/+0.041 | 0.0001/0.926/-0.023 | 0.0061/0.374/-0.318 |
| away incr. R² / p / coef | 0.0080/0.431/-0.200 | 0.0004/0.821/-0.054 | 0.0006/0.784/+0.090 |

*Halftime resilience* (primary metric: pooled):

| | baseline (n=64) | M1 (n=70) | M2 (n=75) |
|---|---|---|---|
| incr. R² / p / coef | 0.0211/0.264/-0.158 | 0.0125/0.327/-0.108 | 0.0000/0.983/+0.002 |

Resilience's pooled incr. R² has now decayed smoothly to exactly zero
(0.0211 -> 0.0125 -> 0.0000) with p rising to 0.983 — as clean a
convergence-to-null trend across three checkpoints as this kind of test
produces. Home/away split's primary points metric remains clearly non-
significant on both sides. A few secondary (non-decision) metrics crossed
p<0.05 this round, but with inconsistent signs across home/away and across
milestones (mostly still mean-reversion-signed, the wrong direction for the
hypothesis) — the pattern expected from uncorrected multiple looks across
~24 metrics x 3 checkpoints, not a coherent signal, and none of them are the
pre-registered primary metric.

**Decision: both original families remain paused.** Per the pre-registered
primary metrics, unchanged. This was, per the stopping rule, the **final**
scheduled retest for both — no further scheduled Stage 0 retesting of
home/away split or halftime resilience is planned.

**Note on E1 resilience — flagged for possible future consideration, not a
reopening of this evaluation.** E1's per-league resilience result has shown
a borderline, positively-signed, not-quite-significant pattern at both M1
(p=0.103) and M2 (p=0.077), unlike E0/SP1 which flip near zero. This is a
narrower, different hypothesis than the one tested here (a Championship-
specific effect, not "resilience in general" pooled across leagues). Per
the stopping rule's scope clarification above, a league-specific hypothesis
would count as a material change and could be scoped as its own new
research question later — it does not reopen or overturn today's pooled
verdict, and is not itself Stage-0-tested here.

## Dixon-Coles: M2-objective validation, implementation audit, and corrected evaluation (2026-07-04)

**Status: investigation complete.** After M2, the question "did the expanded
dataset materially improve the Dixon-Coles baseline?" was investigated in
three stages. This section documents all three explicitly, because stage 3
**supersedes** stage 1's conclusion — the earlier finding was based on a
buggy implementation and should no longer be cited on its own.

### 1. Original (pre-audit) evaluation — superseded, do not cite standalone

Retrained Dixon-Coles on the M2 10-season dataset via `WalkForwardSplit`
(4 expanding folds, train 2,624 -> 10,496 matches) and compared to
B0-market[power]. Findings at the time:
- Rho positive in 11 of 12 fold x league fits (0.011-0.055), same
  wrong-sign anomaly as the original Sprint 3B single-season result — read,
  at the time, as "stable across a 6x training-size range, therefore
  probably a real property of the data, not small-sample noise."
- 1x2 log-loss gap to B0 essentially flat across folds (0.033-0.046),
  **not shrinking** as training data grew 4x within the walk-forward design.
- Provisional conclusion drawn at the time: "further data-volume expansion
  (M3/M4) is unlikely to close this gap — looks like a model-class
  limitation, not a data limitation."

**This conclusion is superseded by section 3 below and should not be
treated as a standing finding.** It was correct that the gap didn't close
with more data *in that implementation* — but the implementation itself
had two confirmed defects (section 2), so "model-class limitation" was not
yet a safe inference from that observation alone.

### 2. Implementation audit — two confirmed defects, both fixed

Before accepting the model-class-limitation conclusion, audited the
implementation against Dixon & Coles (1997) and two independent reference
implementations (dashee87, penaltyblog blogs), covering rho parameterization,
likelihood function, optimization objective, time-decay weighting, and
low-score adjustment scope.

- **Tau lambda/mu swap (confirmed bug).** `_tau()`'s (1,0) and (0,1) cells
  had lambda (home expected goals) and mu (away expected goals) swapped
  relative to the paper and both reference implementations. Confirmed via
  direct fetch of reference source code, not memory alone. The existing
  `test_tau_matches_hand_computed_values_on_special_cells` had encoded the
  *swapped* formula as correct, and the synthetic MLE-recovery test
  simulated and fit using the same (buggy) internal `_tau`, so it only ever
  checked self-consistency, never external correctness — explaining why
  the bug was invisible to the existing suite. Fixed in
  `src/footpred/ml/models/dixon_coles.py`; test corrected; a dedicated
  regression test with hardcoded values added
  (`test_tau_regression_lambda_mu_not_swapped`) that fails under the old
  swapped formula specifically, independent of the corrected hand-computed
  test.
- **Time-decay weighting (confirmed gap, not a bug — a missing feature).**
  The original method's exponential match-recency weight (`exp(-xi*days)`)
  was entirely absent — every match in a training window was weighted
  equally regardless of age, meaning M2's 10-season fit pooled a decade of
  team strength with zero decay. Added as `xi` (default 0.0, backward
  compatible) on both `DixonColesModel` and `DixonColesPredictor`; requires
  a `match_date` column when `xi > 0` (raises otherwise); new tests cover
  the weight formula and a synthetic regime-shift case proving decay
  actually tracks recent form better than no decay.
- Likelihood function, optimization objective (MLE via `scipy.optimize`,
  bounds non-binding), and low-score adjustment scope (exactly the 4
  correct cells) were all confirmed **faithful to the paper** — only the
  two items above were defects.
- All 78 project tests pass after the fix (17 in `test_dixon_coles.py`,
  including 6 new tests added by this audit).

### 3. Corrected evaluation — current, authoritative conclusion

Reran the identical M2 walk-forward comparison with the fixed
implementation, then grid-searched the time-decay rate.

- **Rho: fixed.** Negative in all 12 fold x league fits with corrected tau
  alone (no decay), range -0.018 to -0.077 — squarely in the literature's
  typical range. Confirms the tau swap, not the data, caused the original
  wrong-sign result.
- **ξ grid search (global):** tested [0, 0.0005, 0.001, 0.0018, 0.003,
  0.005] by mean held-out 1x2 log-loss across the 4 folds. Best: **ξ=0.001**
  (~1.9-year half-life), mean log-loss 1.0328 (ξ=0) -> 1.0288 (ξ=0.001) ->
  1.0364 (ξ=0.005, aggressive decay is clearly worse) — a shallow U-shape,
  not "more decay is always better."
- **ξ grid search (per-league):** E0 best ξ=0.0018 (log-loss 0.98980 vs.
  0.99168 at global ξ, **+0.19%**), E1 best ξ=0.0010 (**identical** to the
  global value, +0.00%), SP1 best ξ=0.0005 (1.00749 vs. 1.00773,
  **+0.02%**). Differences are within fold-to-fold noise already observed
  elsewhere (e.g. fold 2's COVID-window anomaly) — **no material
  league-specific tuning benefit; global ξ=0.001 is stable and used as the
  default.**
- **DC vs. B0 gap:** narrows modestly with the fixes — average 1x2 gap
  0.0392 (no decay) -> 0.0352 (ξ=0.001), a ~10% relative reduction, most
  concentrated in the most recent fold (2023-25), where 1x2 calibration
  (ECE) nearly matches B0 exactly (0.0051 vs. 0.0052). **Dixon-Coles still
  loses to B0 on every metric, every fold, even at best ξ** — the fixes did
  not reverse the headline result.

**Revised, current conclusion:** the tau bug and missing time-decay were
real, confirmed implementation defects that were contributing to the
earlier apparent stagnation — fixing them produced a real (if partial)
narrowing of the DC-B0 gap and, more importantly, a now-trustworthy rho
estimate. Dixon-Coles still underperforms the de-vigged market on every
metric even after the fixes, so a genuine gap likely remains — but its true
size was not knowable from the pre-audit implementation, and the earlier
"model-class limitation, not data limitation" framing should be read as
**directionally probably still right, but not established with the
confidence the pre-audit numbers implied.** This is now a fair evaluation
of Dixon-Coles; per the user's call, the investigation is complete and the
model is not being further optimized (e.g. no per-league ξ, no further
grid refinement) — next research effort moves elsewhere rather than
continuing to tune this baseline.

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

## TabularPredictor milestone and the team_form ablation (2026-07-04)

**Status: milestone complete, ablation complete, decision made.** This
section is split into three explicitly separate parts, per how the work
was actually done: a new framework capability, a specific empirical result
produced using it, and the decision that result justifies. Keep these
separate when citing this section — the milestone is a standing capability
regardless of any one ablation's outcome; the ablation result is specific
to `team_form` and does not need to be revisited every time the framework
is used for a different feature family.

### 1. The TabularPredictor milestone

Resolved the structural gap flagged repeatedly since Sprint 4 (no
feature-consuming model existed to run a real Stage 2 ablation against —
B0 only reads odds, Dixon-Coles only reads goals history, `team_form` sat
in every dataset build unused by anything). Built a generic, pluggable
tabular-model `Predictor`:

- **Dependency added:** `scikit-learn>=1.3` (`pyproject.toml`), same
  addition pattern as `scipy` for Dixon-Coles.
- **`src/footpred/ml/models/tabular.py`:** two-layer design.
  `TabularEstimator` is the pluggable inner contract, deliberately shaped
  to match the sklearn classifier convention (`fit`/`predict_proba`/
  `classes_`) so sklearn, XGBoost, LightGBM, and CatBoost's
  sklearn-compatible classes all satisfy it with zero adapter code.
  `TabularPredictor` is the outer `Predictor`-protocol implementer: explicit
  feature-column allowlisting (derived from each feature group's own
  published naming constants, never "everything except known targets"),
  one shared preprocessing pipeline (median-impute -> one-hot `league_key`
  -> scale, fit on train only), one estimator per market, output columns
  reindexed into `BacktestRunner`'s required selection order regardless of
  the estimator's own `classes_` order. Pools across leagues (unlike
  Dixon-Coles's per-league fit) — `league_key` is a feature, not a
  model-fitting boundary.
- **No changes to `BacktestRunner`, `DatasetBuilder`, or `splits.py`** —
  same zero-framework-change integration Dixon-Coles proved out in Sprint 3B.
- **Tests: 89/89 pass** (78 pre-existing + 11 new in `tests/test_tabular.py`):
  leakage-guard (allowlist proven safe against an adversarial frame), train-
  only preprocessing statistics, unseen-league abstention, unseen-team
  *non*-abstention (a genuine advantage over Dixon-Coles — team identity
  isn't a raw feature here, so a brand-new team just gets imputed form
  stats), output-column reindexing against a deliberately-scrambled fake
  estimator, probabilities-sum-to-1, an obviously-learnable-pattern smoke
  test, and an end-to-end unmodified-`BacktestRunner` wiring test.
- **Leakage-safe walk-forward evaluation confirmed working:** ran the
  project's own `assert_no_leakage` guard explicitly against every
  `WalkForwardSplit` fold used in this and the Dixon-Coles evaluation —
  passed globally and per-league on all 4 folds (this check had been
  trusted but not explicitly run earlier in the session).
- **Coverage finding (documented, not fixed — out of this milestone's
  scope):** market-average and all ou_2.5 odds are 0% covered in the
  earliest two walk-forward folds (train windows ending 2019), then
  partially covered (33% -> 50%) as later folds extend past it — consistent
  with the M2 addendum's older-file-format finding. `SimpleImputer` silently
  drops an entirely-uncovered column from its output rather than erroring;
  confirmed non-crashing via a dedicated test, but the effective feature
  count does shrink in those folds for the affected columns.

First head-to-head result with everything included (`odds_core`+`team_form`
vs. B0 vs. corrected Dixon-Coles, mean across 4 folds): Tabular's 1x2
log-loss (0.99875) sits between B0 (0.99358) and Dixon-Coles (1.02878) —
beats DC decisively on log-loss/Brier every fold/market, closes roughly 85%
of DC's gap to B0. (Calibration specifically was mixed: DC's ECE edged
Tabular's in the two most recent, largest-training folds, where DC's
time-decay fix had its biggest calibration benefit.) This result mixes
`odds_core` and `team_form` together, which is exactly why the ablation
below was needed before drawing any conclusion about `team_form` itself.

### 2. The team_form ablation result

Compared `Odds-only`, `Form-only`, and `Odds+Form` head to head (same
`WalkForwardSplit` folds, same preprocessing, same metrics), then reran
`Odds-only` vs. `Odds+Form` across a `C` grid ([0.01, 0.03, 0.1, 0.3, 1.0,
3.0, 10.0]) to make sure an untuned default regularization wasn't
mischaracterizing the result.

- **Odds-only beats Odds+Form on the primary 1x2 market — consistently,
  not marginally.** At default `C=1.0`: mean log-loss 0.99618 (Odds-only)
  vs. 0.99875 (Odds+Form), a gap present in **all 4 folds** (deltas
  -0.00296, -0.00433, -0.00193, -0.00108 — always the same sign, never
  flipping). At each config's own best `C` (both preferred `C=0.01`, the
  most-regularized point tested): gap narrows to -0.00141 mean but **stays
  negative in all 4 folds**.
- **`team_form` alone (Form-only) does carry real signal** — clearly beats
  a naive uniform-probability baseline (mean 1x2 log-loss 1.03528, vs.
  ln(3)=1.0986 for a coin-flip-equivalent guess) — but that signal does
  **not add marginal value once odds are present**.
- **C-grid retuning does not rescue `team_form` — the finding is reinforced,
  not weakened.** Swept `Odds+Form` across the entire `C` grid against
  `Odds-only`'s own best `C`: the gap is negative at every single tested
  `C` (-0.00141 at C=0.01, widening to -0.00492 at C=10.0) — there is no
  regularization strength in a 1000x range where adding `team_form` helps
  the primary market.
- **`ou_2.5` is effectively neutral/noise-level, not a supporting result for
  `team_form`.** At default C, the gap is small and consistently negative
  (-0.00082 mean); at each config's best C, it's a wash — tiny positive in
  2 of 4 folds, tiny negative in 2, magnitudes (~0.0002) indistinguishable
  from noise. This market simply doesn't provide evidence either way.
- **Coefficient interpretation (fold 4, largest training set, 1x2):** in
  Form-only, the strongest features are goal-scoring-rate stats
  (`home_form_gf_last10`, `home_form_gd_last10`, `away_form_gf_last10`),
  all correctly signed. In Odds+Form, those same coefficients collapse
  (`home_form_gf_last10`: 0.084 -> 0.011, ~87% shrinkage) — most of
  `team_form`'s apparent signal is a subset of what market odds already
  encode. What little remains shifts toward sample-count features
  (`away_form_n_last5/10`), a plausible (not confirmed) residual
  "how much history do we have on this team" signal rather than a
  performance signal.

### 3. The decision

- **Current `team_form` features (rolling pts/gf/ga/gd/n, last-5/last-10,
  both sides) should NOT be promoted as value-adding features on top of
  odds.** This is the first real Stage 2 ablation result in the project's
  history — Sprint 4's whole paused-feature-registry effort never had a
  tool to reach this stage before. `team_form` stays in the codebase
  (it's still used and tested elsewhere, e.g. Dixon-Coles doesn't use it,
  but nothing here removes the feature group itself) — it's just not
  being promoted as improving the 1x2/ou_2.5 prediction task over odds
  alone.
- **`TabularPredictor` is kept as an important new framework capability,
  independent of this specific result.** It's the first working Stage 2
  ablation tool this project has had; its value doesn't depend on
  `team_form` in particular passing or failing.
- **Future feature work must clear this same ablation pattern before being
  promoted** — Odds-only vs. Odds+candidate-feature, same walk-forward
  folds, checked for consistency across folds (not just a mean), and a
  brief regularization-sensitivity check (a small `C`-style sweep) before
  accepting a negative *or* positive result at face value. This is now the
  Stage 2 half of the evidence gate that [[feature_engineering_discipline]]
  and the Stage 0 work only ever described in principle.

## Bookmaker-divergence ablation and the odds-coverage finding (2026-07-04)

**Status: complete.** Chosen via an explicit information-theoretic comparison
of research directions after the `team_form` result (see project memory)
— the reasoning: any feature derived purely from public historical results
is likely already subsumed by the market, so the search should prioritize
signals that are structurally different in kind, not just another slice of
the same information. Bookmaker divergence (`div_*`: Bet365 minus
market-average, de-vigged) was picked as the best cost-adjusted candidate —
already computed, zero implementation cost, and a meta-signal about
disagreement between pricing sources rather than another proxy for team
quality. Tested `Consensus-only` vs. `Consensus+Divergence` vs.
`Divergence-only`, same `WalkForwardSplit` folds/preprocessing/metrics as
every prior evaluation, segmented by league, odds band, and market.

### The odds-coverage finding (general — affects ALL future odds-derived research, not just this test)

**Divergence requires both Bet365 and market-average odds to exist for a
match; market-average coverage is 0% in the training windows for
`WalkForwardSplit` folds 1-2 (roughly pre-2019).** This means
`Consensus-only` and `Consensus+Divergence` were **mathematically identical**
in folds 1-2 (`SimpleImputer` silently drops the all-NaN divergence columns,
collapsing both configs to the same design matrix — confirmed by identical
log-loss to 5 decimal places), and `Divergence-only` couldn't be fit at all
in those folds (zero usable features). **Only folds 3-4 actually tested the
divergence hypothesis** — half the intended statistical power, silently,
unless checked for explicitly. This is a general constraint on **any** future
research using market-average odds or anything derived from cross-bookmaker
comparison on this dataset as currently imported: expect roughly the first
half of the walk-forward history to contribute little or nothing to such
tests, and check for degenerate (identical-output) folds before trusting an
"inconclusive" result — it may just mean the data wasn't there to test with,
not that the hypothesis is genuinely untestable.

### Divergence classification

**Not promoted — and deliberately not filed as a clean rejection like
`team_form`.** Classified precisely as:
- **Not promoted** — no evidence it adds usable value over consensus odds.
- **Underpowered due to market-average coverage gaps** — only 2 of 4
  walk-forward folds provided any real test; the other 2 were degenerate.
- **Mildly negative on 1x2 where testable** — incremental gain −0.00050
  (fold 3) and −0.00169 (fold 4); notably, the effect got *more* negative
  in the fold with *more* divergence coverage (50% vs. 33%), not less —
  weak evidence this isn't just a data-starvation problem.
- **Tiny/mixed on ou_2.5** — incremental gain +0.00078 (fold 3), +0.00058
  (fold 4): small, inconsistent in direction with 1x2, plausibly noise.
- **Worth revisiting only if historical market-average odds coverage
  improves, or more bookmaker sources are added** — this is a data
  availability gate, not a closed research question. Unlike `team_form`
  (four well-powered, consistently-signed folds — a real null result),
  divergence's evidence base was too thin to conclude the hypothesis is
  wrong, only that it isn't currently promotable.

**Secondary finding:** `Divergence-only` (5 columns) clearly underperforms
`Consensus-only` (44 columns) as expected — but still clearly beats a
uniform-guess baseline (log_loss 1.06767 vs. ln(3)=1.0986 for 1x2), so
divergence is not pure noise in isolation, just far less informative than
price level alone.

**Code:** `src/footpred/ml/models/tabular.py` gained two new resolvable
feature groups, `odds_consensus` and `odds_divergence` (a partition of
`odds_core`'s existing columns, not new data) — needed to isolate divergence
from the price level for this test. 90/90 tests pass (2 new, verifying the
partition is exact and non-overlapping).

## Cross-market coherence and expanded segmented analysis (2026-07-04)

**Status: complete — diagnostic only, one candidate flagged for its own
future milestone, nothing promoted.** Run as the "cheap diagnostic pair"
identified during the post-divergence strategic research-direction review:
(1) whether the 1x2 and O/U 2.5 markets are mutually coherent, and (2)
whether segmenting by league/odds-band/time-into-season reveals value the
pooled `team_form` and divergence ablations missed. Both reused the
existing `TabularPredictor`/`WalkForwardSplit` harness unchanged; `tabular.py`
gained one small, disciplined addition — an explicit `extra_columns`
allowlist parameter, letting one-off engineered analysis columns (like the
coherence measure below) be tested without prematurely promoting them to a
registered `FeatureGroup`. 92/92 tests pass.

**Cross-market coherence — primary result: null.** Defined
`incoherence = actual market P(over 2.5) − 1x2-implied P(over 2.5)`, backing
out implied (λ, μ) from the 1x2 market via independent-Poisson root-finding
(deliberately not reusing Dixon-Coles's own fitted ρ, to keep this
self-contained). Pre-registered O/U 2.5 as the primary target, 1x2 as
secondary/diagnostic-only. As expected from the general odds-coverage
finding above, O/U odds don't exist at all pre-2019 (any bookmaker), so
folds 1-2 were correctly skipped rather than forced — only folds 3-4 tested
anything. **On the primary O/U target, the effect is negligible in both
folds** (-0.00073, -0.00005) — no evidence of value, judged by the agreed
framework (consistency, direction, effect size relative to observed noise)
rather than a fixed threshold.

**Cross-market coherence — secondary result (1x2): the one live thread,
explicitly not promoted.** The same incoherence measure showed a
consistent, positive effect on 1x2 in both folds (+0.00207, +0.00485) —
larger in magnitude than any effect observed this session, and, unlike
every noise pattern found so far (the SP1 resilience fluke, the home/away
split's per-league flukes — all of which *shrank* as more data arrived),
this one grew from fold 3 to fold 4. The expanded segmented analysis (below)
found this pattern moderately consistent across league and season-third
segments too, not concentrated in one slice. **This is being deliberately
NOT treated as an accepted finding.** It was pre-registered as
secondary/diagnostic-only, evaluated on the same thin 2-fold evidence base
as the null primary result, and "an interesting secondary result with a
plausible story" is exactly the shape of finding the primary/secondary
pre-registration split exists to keep in check. **Classified as a candidate
for its own new, freshly pre-registered confirmatory milestone** — 1x2 as
the primary target next time, its own success/failure criteria decided
before running, not inherited from this run.

**Expanded segmented analysis — reinforces, does not overturn, the existing
verdicts:**
- **`team_form`: the pooled rejection is reinforced, not weakened.** Re-sliced
  across all 4 folds (full statistical power, unlike the divergence/coherence
  segments below) by league, odds band, and a new time-into-season tertile
  axis — every single 1x2 segment is negative; ou_2.5 is negative everywhere
  except one noisy SP1 cell (mean smaller than its own standard deviation,
  i.e. not a real effect). No hidden pocket of value found anywhere.
- **No E1-specific `team_form` effect found — a concrete data point against
  the long-term roadmap's E1-specific proto-xG bet.** If thinner modeling
  investment in the Championship let scoreline-derived signal through
  anywhere, `team_form` would be the place to see it first. It doesn't show
  up: SP1, not E1, has the least-negative effect on both markets.
- **Divergence: unchanged.** Re-slicing folds 3-4 (only 2 data points per
  cell) doesn't add real statistical power — mostly redisplays the same two
  numbers already reported, grouped differently. Still classified exactly as
  before: not promoted, underpowered due to coverage, revisit-gated on
  future coverage improvements.
- **Coherence, segmented:** primary (O/U) stays negligible everywhere.
  Secondary (1x2) shows up positively across most league/season-third cells
  (weakest in E1) — informative for scoping the follow-up milestone, not a
  basis for promotion on its own.

**How this steers what comes next:** the coherence→1x2 secondary finding is
the only actionable thread; the next milestone should scope and run a fresh,
primary-target, pre-registered confirmatory test of it before any promotion
decision. Everything else (`team_form`, divergence, the E1-inefficiency
hypothesis) is now on firmer footing to leave as-is than before this
diagnostic pair was run.

## Corrected confirmatory 1x2-coherence milestone (2026-07-04) — provisionally promoted

**Status: complete.** Before running this, the project stepped back for a strategic reassessment
(not just "what's next") of the entire research program — see
`docs/RESEARCH_RETROSPECTIVE.md` for the full reasoning. That review surfaced a design flaw in the
original coherence diagnostic: implied goals had been backed out assuming independent scoring
(ρ=0), when the audited Dixon-Coles model's own fitted ρ is small but reliably negative. This
milestone reruns the test correctly.

**Design deviation, decided before seeing results:** O/U odds (any bookmaker) are structurally
absent before ~2019 — already known from the divergence ablation. Reusing the standard 4-fold
`WalkForwardSplit` over the full 10-season history would waste two folds that cannot test this
hypothesis at all. The test population for this milestone is explicitly **"matches with usable 1x2
+ O/U bet365 odds"** (7,870 matches, 2019-08-02 to 2025-05-25, all three leagues consistently
covered) — not the full database — evaluated with 5 expanding folds (~1 season/block) instead of 2
real folds out of 4.

**Correction:** implied (λ, μ) and the implied O/U probability now use the audited Dixon-Coles τ
function with each fold's leakage-safe, fitted per-league ρ (DC fit on full goal history, no odds
needed, cut off strictly before each fold's test window). 1x2 promoted to the pre-registered
primary target (was secondary in the original diagnostic); O/U 2.5 is secondary this time.

**Result:** positive in 4 of 5 folds (mean +0.00246 at default regularization). A C-grid check
(mirroring `team_form`'s discipline exactly) found the effect never collapses or reverses across a
1000x regularization range (mean gain 0.00213–0.00238), with the identical 4-of-5 sign pattern at
every point in the grid, and Brier/ECE improving alongside log-loss. The ρ-correction itself turned
out to matter little in practice (fitted ρ values are small) — worth checking rigorously regardless,
since we couldn't have known that in advance.

**Classification: provisionally promoted, pending independent replication** — a new fourth tier
introduced specifically because this result didn't fit cleanly into rejected/promoted/inconclusive.
Full definition and reasoning in `docs/RESEARCH_RETROSPECTIVE.md`'s methodology section. In short:
this is the strongest, most regularization-stable positive result the project has produced, but one
fold consistently disagrees, the effect sits at the edge of (not clearly beyond) this project's
observed noise band, and the evaluation is necessarily restricted to the post-2019 subset — short of
the confidence bar `team_form`'s rejection earned.

**Confirmation path (general, not tied to this or any specific future milestone):** promotes to
fully **promoted** if independently replicated on any data that played no role in discovering this
signal — new seasons, additional leagues, or a different compatible dataset all qualify equally;
independence is what matters, not which kind of new data it is. Reclassifies to **not confirmed** if
that replication fails to reproduce the effect. Whenever such data becomes available for any
reason, rerunning this exact test (unchanged methodology) on the independent portion is the natural
next occasion — this is not exclusively coupled to a future M3/M4-style data-expansion milestone.

## Draw-tendency residual: closure test for the team-scoreline-derived category (2026-07-04)

**Status: complete — clean rejection, category formally closed.** Scoped explicitly as a closure
test, not an edge candidate, after a full strategic re-ranking of remaining research directions
(BTTS/HT-FT wiring downgraded on discovering no BTTS/HT-FT odds exist in the data source at all;
draw tendency selected as the cheapest remaining test, reusing 100% existing infrastructure — the
audited Dixon-Coles model, `TabularPredictor`, the 1x2 market already wired).

**Feature and leakage safety:** `src/footpred/ml/models/draw_residual.py` (new, not a registered
`FeatureGroup`) computes, per fold, one Dixon-Coles fit per league on training data only, then each
team's mean (actual draw indicator − DC-predicted draw probability), pooled across venue (no
venue-split, per the agreed scope). Training rows get a leave-one-out average, excluding that
match's own contribution to its own team's residual — the same self-exclusion discipline
`team_form`'s `.shift(1)` applies, adapted to a fold-level rather than per-match-rolling
construction. Test rows use the plain training-window average. 5 new tests cover leave-one-out
arithmetic, no self-outcome leakage (proven via a mocked-prediction test isolating the algebraic
cancellation from Dixon-Coles's own fit-sensitivity), test rows depending only on training-window
residuals, and output shape/bounds correctness. 97/97 tests pass.

**Evaluation:** same 4-fold, full-history `WalkForwardSplit` and `Odds-only` baseline `team_form`
was tested against, for maximum comparability to the result this closes out — no coverage
restriction was needed here (unlike the coherence milestones), since 1x2 odds and goals data are
both available across the full 10-season history.

**Result:** negative incremental gain in all 4 folds at default regularization (magnitudes
0.00004–0.00244, at or below this project's established noise band). The regularization-sensitivity
check (C = 0.01–10.0, mirroring `team_form`'s discipline) confirmed the rejection: negative at every
point in the grid, gap widening (not narrowing) as regularization weakens (−0.00040 at best-C down
to −0.00268 at C=10) — the same overfitting-to-noise signature seen in `team_form`'s own C-grid. No
metric supported the candidate (log-loss, Brier, ECE all favored or were indistinguishable in favor
of Odds-only). A secondary check restricted to draw-specific binary log-loss also worsened in every
fold — the feature didn't even improve calibration on the one outcome it targeted.

**This formally closes the team-scoreline-derived hypothesis category** — five independently
designed tests (home/away split, halftime resilience, `team_form`, Dixon-Coles as a standalone
model, draw-tendency residual), all failed or added no value, several confirmed by a full
regularization sweep. See `docs/RESEARCH_RETROSPECTIVE.md`'s Core Finding section for what this
means for future proposals in this category — not automatically disqualified, but requiring a
specific, articulated reason to expect a different outcome than five-for-five.
