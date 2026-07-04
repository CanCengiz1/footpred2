# FootPred Research Retrospective

## Purpose and scope

This document is the project's **research memory** — separate from `ROADMAP.md`, which tracks
future milestones and execution. Where `ROADMAP.md` answers "what are we doing next and how did
the last milestone go," this document answers "what have we learned, and why do we believe it."

Three things this document is for:

1. **Preserve the reasoning behind research decisions**, not just their outcomes. A rejected
   hypothesis is only useful to future work if the *mechanism* of its rejection is recorded —
   otherwise a plausible-sounding idea gets re-proposed and re-tested from scratch.
2. **Prevent repeated work.** Before proposing a new feature or research direction, check here
   first. Several ideas in this project looked promising until existing evidence (often from a
   *different* experiment than the one that would naturally test them) already argued against
   them.
3. **Document the methodology**, independent of any one result — the evidence discipline this
   project has built up is itself a durable asset, arguably more valuable long-term than any
   single feature verdict.

**Update policy:** this document changes only when a later milestone genuinely changes one of its
conclusions (a reversal, a new confirmatory result, a materially different dataset). It is not
updated after every experiment — that is what `ROADMAP.md` and project memory are for. This
version is the initial retrospective, written after the Data Expansion phase, the Dixon-Coles
audit, the `TabularPredictor` milestone, and the first round of Stage 2 ablations.

---

## Table of contents

1. [Core finding](#core-finding)
2. [Research methodology](#research-methodology)
3. [Falsified hypotheses](#falsified-hypotheses)
4. [Provisionally promoted findings](#provisionally-promoted-findings)
5. [Corrected engineering findings (not hypotheses)](#corrected-engineering-findings-not-hypotheses)
6. [Open and plausible hypotheses](#open-and-plausible-hypotheses)
7. [Directions deprioritized or ruled out](#directions-deprioritized-or-ruled-out)
8. [Standing infrastructure and capabilities](#standing-infrastructure-and-capabilities)
9. [How to use this document](#how-to-use-this-document)

---

## Core finding

The single most important result of this project so far is not any individual feature's
rejection — it is the **convergent, repeated evidence that de-vigged market odds are extremely
hard to beat with information the market can also see.** Every scoreline-derived signal tested
(team-specific home/away split, halftime resilience, rolling recent form, Dixon-Coles as a
standalone goals model, and a Dixon-Coles-residual draw tendency) has either failed outright or
added no measurable value once market odds are present. This is not a string of unrelated negative
results — it is the same underlying fact surfacing five separate times, through five different
experimental designs, each with its own robustness check. It should be treated as the project's
central empirical finding, and it is the lens every future research direction should be evaluated
through: **does this introduce information genuinely different from what public historical
results already encode, or is it another way of re-deriving the same thing the market has already
priced?**

**The team-scoreline-derived hypothesis category is now formally closed.** Five independently
designed tests of "does something computable from a team's own historical match results add value
beyond market odds" have all failed, several with a regularization-sensitivity check confirming
the rejection wasn't an artifact of one hyperparameter choice. A future proposal in this category
should not be treated as automatically disqualified — but it should come with a specific,
articulated reason why it would break a five-for-five pattern, not just optimism that a new
transform of the same underlying information will fare differently. See
[Falsified hypotheses](#falsified-hypotheses) for the full account of each test, and the closing
note there for exactly what would justify reopening this category.

---

## Research methodology

This section documents *how* the project evaluates ideas — durable practice, independent of any
one result. Every methodology point below was learned from a specific failure or near-miss, not
designed in the abstract.

### Evidence before implementation (Stage 0)

No feature family gets leakage-safe pipeline code before it clears a cheap existence test against
data already in hand. Two supporting rules, both learned the hard way:

- **A Stage 0 test must target the exact claim the feature depends on, not a proxy claim that
  merely sounds related.** The first home/away split test asked "is there a statistically
  significant team × venue interaction" (a population-heterogeneity claim) when the feature
  actually only needed "does venue-conditioned history carry predictive information" (a weaker,
  different claim). Conflating the two nearly caused a valid feature family to be rejected on the
  wrong test. The fix — a corrected split-half predictive test — still failed, but for the right
  reason this time.
- **Prefer unconditional, continuous measures over sparse conditional event rates**, and **prefer
  stable behavioral features over memorizing rare outcomes.** A feature should capture a
  persistent tendency using the full sample, not a fact reconstructed from a handful of rare label
  occurrences.

### Evidence during promotion (Stage 2 ablation)

Existence isn't enough — a feature must beat the same model without it on held-out data before
being promoted. This stage was **theoretical from Sprint 4 through the Dixon-Coles audit** — no
model in the codebase could consume arbitrary features (B0 only reads odds; Dixon-Coles only reads
goals history) — until `TabularPredictor` was built specifically to close this gap. The first real
Stage 2 ablation (`team_form`) produced a negative result for a feature that had already shipped
since Sprint 3A, which is the point: nothing gets a pass just because it predates the tool that can
properly test it.

### Primary vs. secondary endpoints, decided before running

Every ablation since `team_form` pre-registers exactly one primary metric that decides the
promotion call, and treats every other market/segment/metric as diagnostic only. This discipline
was tested for real during the cross-market coherence analysis: the secondary (1x2) result was the
single most interesting number produced all session — consistent, growing rather than shrinking
with more data — and it was still not promoted, because it wasn't the pre-registered primary
target and the evidence base was thin. That is exactly what the discipline is for.

### Judging effect sizes without a fixed numeric threshold

Early ablations used a fixed log-loss threshold as part of the promotion bar. This was
deliberately dropped after the `team_form` C-grid check, on the grounds that a threshold selected
partly from prior experiments in the same project risks looking data-driven rather than
pre-specified. Results are now judged qualitatively but consistently, on:

- **consistency of sign across all informative folds** (not a single fold, not just the mean),
- **direction relative to what the hypothesis predicts**,
- **effect size relative to the noise this project has now repeatedly observed** in this exact
  pipeline (roughly 0.0005–0.005 log-loss units has shown up as noise multiple times — a result
  needs to look different from that band, not clear an arbitrary number),
- **trajectory across data-growth checkpoints** — a real effect should hold or strengthen as more
  data arrives; several rejected effects visibly *shrank* toward zero instead (see below).

### A fourth classification tier: provisionally promoted, pending independent replication

The original three-way outcome for an ablation — rejected, promoted, or inconclusive/underpowered —
turned out not to have a good home for a result that is real by every check this project applies
(consistent across the majority of informative folds, survives a regularization sweep without
collapsing or reversing, improves multiple metrics together) but has only ever been evaluated on
one body of data. Forcing that into "promoted" overstates confidence that hasn't actually been
earned yet; forcing it into "inconclusive" understates a result that is meaningfully different from
this project's established noise band. A fourth tier was introduced to describe it honestly:

- **Provisionally promoted** — a robustness-checked positive result (survives a regularization/
  sensitivity sweep, coherent across metrics, majority-consistent sign across informative folds)
  that has **not yet been independently replicated** on data that played no role in discovering it.
  Usable in further experiments as a live candidate; not yet an established finding.
- **Promoted** — a provisionally promoted result that **has** been independently replicated on
  previously unseen data. The defining property is **independence, not chronology or data source**:
  newly imported seasons, additional leagues, a different compatible historical dataset — any of
  these count, as long as the replication data was not involved in discovering the original signal.
  A later season becoming available is not privileged over, say, a new league being added; what
  matters is that the data wasn't part of the original search.
- **Not confirmed** — independent replication was attempted and failed to reproduce the effect.
  Treated with the same respect as any other null result — not silently retried until it works.

This is deliberately a general framework, not coupled to any one future milestone (e.g. the next
Data Expansion checkpoint) — whatever independent dataset becomes available first is the natural
occasion to attempt confirmation, and this section should be updated whenever that happens for any
provisionally promoted finding, not just the one that motivated adding this tier.

### Leakage discipline

Every temporal split — whether `GroupFractionSplit`'s single 70/30 cut or `WalkForwardSplit`'s
rolling folds — is checked with the project's `assert_no_leakage` guard before being trusted, not
assumed correct from the split strategy's own design. This was initially trusted implicitly for
ad hoc walk-forward fold assignments in analysis scripts; it is now run explicitly every time,
after the gap was noticed and closed mid-session.

### Segmented analysis is diagnostic, never confirmatory

Slicing an ablation's results by league, odds band, or time-into-season can reveal (or rule out) a
pooled null hiding local heterogeneity. It has never been allowed to promote a feature on its own —
a segment can only generate a fresh hypothesis, which then needs its own dedicated, pre-registered
confirmatory test. This matters because the segment space is large (league × band × season-third ×
market × candidate feature easily exceeds 100 cells) and a false discovery is cheap to manufacture
by accident if segment-level results are treated as evidence in themselves.

### Coverage checks before trusting "inconclusive"

Two separate ablations (bookmaker divergence, cross-market coherence) turned out to have real,
substantial data-coverage gaps that silently degrade statistical power — market-average odds and
all O/U-2.5 odds are effectively absent before ~2019 in the current dataset. An "inconclusive"
result can mean the hypothesis is wrong, or it can mean roughly half the intended test folds
contributed nothing. These are checked explicitly (verifying non-degenerate, non-identical fits
per fold) rather than assumed.

### Auditing implementations against the literature before concluding "model limitation"

A model that looks like it has hit a hard ceiling should be checked against its own specification
before that ceiling is accepted as a fact about the world. Dixon-Coles's fitted correlation
parameter came out with the wrong sign relative to the published literature — a red flag that was
initially (incorrectly) read as "a real property of this data." A direct audit against the
original paper and two independent reference implementations found a genuine implementation
defect (see below). The lesson generalizes: a theoretically surprising result is itself evidence
worth checking against a simpler explanation (a bug) before being accepted as a discovery.

### Data-expansion discipline

Growing the dataset is not free of judgment calls either:

- **Depth before breadth, and the existing data source exhausted before a new one.** More seasons
  of the leagues already in the database, before more leagues, before a fundamentally new provider.
- **A stopping rule for repeated retests.** Once a paused feature family has been retested against
  a data-volume milestone, further retests are not scheduled indefinitely — a family gets one
  further passive confirmatory check at the next milestone, and then scheduled retesting stops,
  regardless of outcome. This was adopted specifically to avoid a slow-motion form of optional
  stopping (repeatedly re-testing the same null hypothesis at successive checkpoints until
  something clears a threshold by chance).
- **The stopping rule only covers scheduled retests of the *current* hypothesis** — a material
  change in the hypothesis, feature definition, available data, data source, or methodology is a
  new research question, not a continuation of a closed one.

---

## Falsified hypotheses

Hypotheses below are considered **settled** in the sense that: the test targeted the exact claim
the feature needed, the evaluation was adequately powered (multiple folds, consistent sign,
often a robustness check across a hyperparameter grid), and — where applicable — the effect
*shrank toward zero as more data arrived* rather than staying flat or strengthening, which is the
signature of a genuine null rather than an underpowered true effect.

### Team-specific home/away split

**Claim tested:** a team's own historical home/away split performance (points, goals-for,
goals-against) carries predictive information beyond the team's venue-agnostic average.

**Result:** failed under two independently-designed tests — a population-level interaction
significance test, and (after that test was judged to answer the wrong question) a corrected
split-half predictive test. The corrected test also failed at the original single-season baseline,
and failed *more decisively* after two rounds of data expansion (1 → 5 → 10 seasons per league):
incremental R² and significance both moved further from the promotion bar as data grew, not closer.

**Why considered settled:** two structurally different hypotheses (population heterogeneity,
predictive value) converged on the same answer, and the effect trended toward null with more data
rather than toward significance — the opposite of what a real, underpowered effect would show.

### Halftime resilience (continuous reformulation)

**Claim tested:** a team's historical tendency to outperform or underperform in the second half
relative to the first (second-half GD minus first-half GD, averaged over all matches, not
conditioned on a rare trailing-at-halftime subset) carries predictive information.

**Result:** incremental R² decayed smoothly across three data-volume checkpoints — roughly
0.021 → 0.013 → 0.000 — with the significance moving further from the bar at each step. A
single-season, single-league fluke (the largest apparent effect at baseline) was later shown to
evaporate almost completely once more data arrived for that same league, illustrating exactly the
trajectory a spurious result should show.

**Why considered settled:** same reasoning as the home/away split — consistent trend toward zero
across three genuine checkpoints, not a single underpowered snapshot.

### `team_form` (rolling recent-form features) adding value over market odds

**Claim tested:** rolling points/goals-for/goals-against/goal-difference over a team's last 5 and
10 matches adds predictive value on top of de-vigged market odds.

**Result:** the best-powered rejection in the project. Failed at default regularization (negative
incremental gain in all 4 walk-forward folds, both markets), and — critically, since a fair
retuning check was requested before accepting the result — **failed across an entire
regularization grid spanning three orders of magnitude** (C = 0.01 to 10.0), narrowing but never
reversing. Coefficient inspection explains the mechanism: the strongest raw predictors (recent
goal-scoring rate) lose roughly 87% of their magnitude once odds are added as competing features —
the signal is real in isolation (it clearly beats a naive baseline) but almost entirely redundant
with what the market already prices.

**Why considered settled:** consistent sign across every fold and every point in a wide
regularization sweep, plus a mechanistic explanation (coefficient collapse) for *why* it fails, not
just *that* it fails. This is the template every subsequent ablation has been measured against.

**Segmented re-check (later milestone):** re-sliced by league, odds band, and time-into-season —
every segment for the primary market was negative, with no league-specific exception. Notably, no
E1 (Championship)-specific effect appeared; if anything SP1 showed the least-negative effect, not
E1. This is relevant evidence (not conclusive) against the long-term roadmap's hypothesis that E1
is specifically under-modeled relative to E0/SP1 — see [Open and plausible hypotheses](#open-and-plausible-hypotheses).

### Draw tendency as a Dixon-Coles residual — the closure test for this category

**Claim tested:** a team's historical tendency to draw more or less often than the audited
Dixon-Coles model predicts (a residual — actual draw indicator minus DC's predicted draw
probability, pooled across venue, leave-one-out on training rows to avoid a match contributing to
its own feature) carries incremental predictive value beyond de-vigged market odds. Explicitly
scoped and run as the **final closure test** for the team-scoreline-derived hypothesis category,
not as a genuine edge candidate — see the Core Finding section above.

**Result:** failed at default regularization — negative incremental gain in all 4 walk-forward
folds (same 4-fold, full-history split `team_form` was tested on, for maximum comparability),
magnitudes (0.00004–0.00244) sitting at or below this project's established noise band. The
regularization-sensitivity check requested for symmetric rigor confirmed it: negative at every
point across the full C = 0.01–10.0 grid, with the gap **widening** as regularization weakens
(−0.00040 at the best C for both configs, down to −0.00268 at C=10) — the same
overfitting-to-noise signature `team_form`'s own C-grid showed. No metric supported the candidate:
log-loss, Brier, and ECE all favored or were indistinguishable in favor of Odds-only at every
tested C. A secondary check restricted to draw-specific binary log-loss (the exact class this
feature targets) also worsened in every fold — the feature doesn't even improve calibration on
the one outcome it was built to help predict.

**Why considered settled:** consistent negative direction across all 4 folds, a full regularization
sweep that never reverses and gets worse (not better) with less regularization, agreement across
three metrics, and a secondary draw-specific check that confirms rather than complicates the
primary result. The same evidentiary bar `team_form`'s rejection was held to.

**This is the fifth and, for now, final test of the team-scoreline-derived category — see the
Core Finding section for what this closes and what would be required to reopen it.**

---

## Provisionally promoted findings

Results classified under the fourth tier defined in [Research methodology](#research-methodology):
robustness-checked and positive, but not yet independently replicated. See that section for exactly
what "provisionally promoted," "promoted," and "not confirmed" mean and how one graduates to
another.

### Cross-market coherence → 1x2 (ρ-corrected)

**Claim tested:** whether the O/U-2.5 market's price disagrees with what the 1x2 market's implied
scoreline distribution predicts — with that implied distribution now computed via the *audited*
Dixon-Coles model (τ-corrected, using each fold's leakage-safe fitted per-league ρ), superseding an
earlier diagnostic run that had assumed independence (ρ=0). 1x2 was pre-registered as the primary
target this time (it had only ever been tested as a secondary/diagnostic endpoint before).

**Design:** evaluated on the explicit test population of "matches with usable 1x2 + O/U bet365
odds" — 7,870 matches, 2019-08-02 to 2025-05-25, all three leagues consistently covered — rather
than the full 10-season database. This restriction was decided *before* running anything, not
discovered after: O/U odds (any bookmaker) are structurally absent before ~2019, a fact already on
record from the divergence ablation, so reusing the standard 4-fold split over the full history
would have wasted two folds that cannot test this hypothesis at all. Within the restricted, fully
informative population, 5 expanding `WalkForwardSplit` folds were used (~1 season/block) instead of
2 real folds out of 4 — more statistical power at the same computational cost, at the price of
comparability to prior tests' exact fold structure. Dixon-Coles's ρ itself was fit on full goal
history (it needs no odds), cut off leakage-safely at each fold's test-window start.

**Result:**
- Primary (1x2): incremental gain positive in 4 of 5 folds (−0.00063, +0.00241, +0.00189, +0.00552,
  +0.00309; mean +0.00246 at default regularization).
- The ρ-correction changed very little versus the original independence assumption (mean gain
  +0.00278 under ρ=0 on the identical folds) — the theoretical concern that motivated this milestone
  was worth checking rigorously, but the fitted ρ values turned out small enough that it wasn't a
  major confound in practice.
- **C-grid check** (C = 0.01 to 10.0, mirroring the `team_form` discipline exactly): best C=0.01 for
  both baseline and candidate; the effect **never collapsed or reversed** across the full grid
  (mean gain 0.00213–0.00238), and the same 4-of-5 sign pattern held at every single point in the
  grid, not just at best-C. Brier and ECE both improve alongside log-loss at best C.
- Secondary (O/U 2.5) stayed null throughout, consistent with every prior run.

**Why provisionally promoted, not promoted or rejected:** this is the most consistent, most
metric-coherent, most regularization-stable positive result the project has produced — clearly
stronger than the underpowered divergence/original-coherence results, and it does not collapse under
a robustness check the way a spurious effect would. But it falls short of the confidence bar
`team_form`'s rejection earned: one fold (the earliest, smallest-history fold) consistently
disagrees rather than 100% consistency; the mean effect size sits at the edge of, not clearly beyond,
the ~0.0005–0.005 noise band this project has repeatedly observed; the evaluation is necessarily
restricted to the post-2019 odds-covered subset, not the full history; and with only 2-3 features in
play, the C-grid here is a structurally weaker stress test than it was for `team_form`'s 49+ feature
ablation, so "survived the C-grid" carries less evidentiary weight than the same phrase did there.

**Confirmation path:** promotes to fully **promoted** if independently replicated — same feature
definition, same methodology — on any data that played no role in discovering this signal (new
seasons once imported, additional leagues, or a different compatible dataset; independence is what
matters, not which of these it is). Reclassifies to **not confirmed** if that replication fails to
reproduce the effect. Until then, usable as an active candidate in further experiments, not treated
as an established finding.

---

## Corrected engineering findings (not hypotheses)

These are implementation defects, not claims about the world — worth recording precisely because
they were initially mistaken for a genuine research finding.

### Dixon-Coles τ-function λ/μ swap

The low-score correction function had the home/away expected-goals terms swapped on two of its
four special cells, relative to the original 1997 paper and two independent reference
implementations (confirmed by direct fetch of source code, not memory). The bug had gone
undetected because the project's own test suite encoded the swapped formula as correct, and the
synthetic parameter-recovery test simulated and fit data using the same (buggy) internal function —
proving self-consistency, never external correctness. Fixed, with a dedicated regression test
using hardcoded values distinguishable from the swapped result.

**Consequence for interpretation:** the model's fitted correlation parameter had come out
persistently positive (wrong sign vs. the literature's typical small-negative value) across every
prior fit, including after a 10x data expansion — at the time this was read as possible evidence
the positive sign was "a real property of this data." After the fix, the parameter came out
negative in all 12 fold × league fits tested, in the literature's typical range. The apparent
data-driven finding was an artifact of the bug, not a discovery.

### Missing time-decay weighting

The original method's exponential down-weighting of older matches (`exp(-ξ·days)`) was entirely
absent — every match in a training window counted equally regardless of age. Added as a
configurable, backward-compatible parameter (default off). A small grid search selected ξ=0.001
(~1.9-year half-life) as stable across all three leagues (per-league retuning gained <0.2%, judged
not worth the added complexity).

**Consequence:** with both fixes, Dixon-Coles's gap to the market baseline narrowed by roughly 10%
on average, concentrated in the most recent data — but the model still loses on every metric,
every fold, even at its best configuration. The residual gap likely still reflects a genuine
model-class limitation, but that conclusion is now known to be more uncertain than the pre-audit
result implied, since two confirmed defects were contributing to the earlier apparent stagnation.

---

## Open and plausible hypotheses

These have **not** been rejected — either untested, or tested with genuinely insufficient power,
or only indirectly addressed. They should not be re-proposed as if novel, but they also should not
be treated as settled.

*(Cross-market coherence, previously listed here as the project's most promising open thread, has
since been given its own primary-target confirmatory test and reclassified — see
[Provisionally promoted findings](#provisionally-promoted-findings). Draw tendency as a
Dixon-Coles residual, previously listed here as untested, has since been run as the closure test
for the team-scoreline-derived category and reclassified — see
[Falsified hypotheses](#falsified-hypotheses).)*

### Bookmaker divergence (Bet365 vs. market-average, de-vigged)

Whether disagreement between pricing sources carries information the consensus price doesn't.
Mildly negative on the primary (1x2) market where testable, tiny/mixed on O/U — but only 2 of 4
walk-forward folds provided a real test (market-average odds are essentially absent before 2019),
so this is classified as **underpowered, not rejected**. Revisit if historical market-average
coverage improves or additional bookmaker sources are added; do not re-run expecting a different
answer on the same coverage.

### E1-specific market inefficiency (the basis for a proto-xG investment)

The long-term roadmap's argument for acquiring shot/xG-quality data was conditional on E1
(Championship) being less efficiently modeled by bookmakers than E0/SP1, given lower betting
volume and (presumed) lower modeling investment. The one test run so far — re-slicing `team_form`'s
already-null result by league — found no E1-specific effect, and if anything SP1 looked least
efficient by this particular lens. This is **weakening, not disconfirming** evidence: it only shows
that scoreline-derived signal isn't specifically missed in E1, not that a genuinely different
signal (real shot location/quality data) wouldn't be. The proto-xG acquisition remains gated on
this question, not greenlit or cancelled.

### Event-conditioned bucket (comeback tendency, lead-protection) and the original HT/FT team-signature idea

Never tested. Both are goal-history-derived by construction, so the mechanism behind `team_form`'s
failure plausibly applies — but "plausibly applies" is a reason to deprioritize, not a substitute
for a test. If ever revisited, both would need shrinkage-based estimation given known small-sample
issues (documented in the original Team DNA proposal), and both would need to clear the same
Stage 0 → Stage 2 pipeline as everything else, not be assumed pre-rejected.

---

## Directions deprioritized or ruled out

Distinguished from the falsified-hypotheses section above: these were reasoned away, largely
before implementation, rather than tested and rejected. Recorded so the reasoning isn't lost and
the ideas aren't re-proposed as if new.

- **Further Dixon-Coles tuning.** The ξ grid showed diminishing and eventually negative returns to
  further decay tuning; per-league retuning gained under 0.2%. Its role going forward, if any, is
  as a potential feature input to a richer model, not a continued target of optimization.
- **Any new feature built purely from historical scorelines** (more rolling windows, ELO-style
  ratings, alternative decay weightings, further Dixon-Coles residuals). Five independently
  designed tests — home/away split, halftime resilience, `team_form`, Dixon-Coles as a standalone
  model, and the draw-tendency residual — have all failed or added no value, several confirmed by
  a regularization sweep. The category is formally closed (see the Core Finding section); a new
  proposal here needs a specific reason it would break that pattern, not just a new transform of
  the same information.
- **Pure data-volume expansion (further M3/M4-style growth) as an end in itself.** Demonstrated
  directly: fixing Dixon-Coles's two implementation defects mattered far more than a 10x increase
  in training data. More data remains useful for specific, targeted reasons (a richer model that
  demonstrably wants it, a specific segment that needs more depth to test), but "more data
  improves things" is not itself a justification anymore.
- **Fixture congestion / rest-days**, proposed and then self-critiqued out before implementation:
  on reflection, rest-day context is *more* publicly salient than statistical form (broadcast
  commentary routinely states "third match in eight days" before kickoff), making it an unlikely
  candidate for being under-priced — and the project's own data would measure it incompletely
  regardless (league fixtures only, no cup/continental competitions), biasing any test toward a
  false null. Recorded as an example of an idea that didn't survive scrutiny before code was
  written for it, which is the point of doing that scrutiny.

---

## Standing infrastructure and capabilities

Durable tools this research has produced, independent of any single result:

- **Ingestion pipeline** — flexible column mapping, conservative entity resolution, idempotent
  imports; validated across 10 seasons and three leagues with zero unresolved entity conflicts.
- **Leakage-safe evaluation harness** — `GroupFractionSplit`, `WalkForwardSplit`, and
  `assert_no_leakage`, the last now applied explicitly rather than trusted implicitly.
- **Corrected Dixon-Coles** — paper-faithful τ function, configurable time-decay (validated
  ξ=0.001), stable across leagues.
- **`TabularPredictor` / `TabularEstimator`** — the project's first feature-consuming model and
  first working Stage 2 ablation tool, deliberately shaped to accept any sklearn-compatible
  estimator (logistic regression today; gradient boosting, XGBoost, LightGBM, CatBoost require
  zero adapter code if adopted later). Includes an explicit feature-column allowlist mechanism
  (never "everything except known targets") and an `extra_columns` escape hatch for one-off
  engineered analysis columns that haven't been promoted to a registered feature group.
- **Paused-feature registry design** — documented in `ROADMAP.md`, not yet implemented as running
  code; specifies retest thresholds and a strict eligibility → retest → (pass) → backlog gate that
  never skips straight to implementation.
- **`draw_residual.py`** — leakage-safe Dixon-Coles-residual feature construction (one DC fit per
  league per train/test split, leave-one-out on training rows), the tool used for the final
  team-scoreline-derived closure test. Not a registered `FeatureGroup` (it didn't clear ablation),
  but reusable machinery if a differently-scoped residual feature is ever proposed with a specific
  reason to expect a different outcome.

---

## How to use this document

Before proposing a new research direction or feature:

1. **Check the falsified-hypotheses section** for anything mechanistically similar. If the new
   idea is "another way of deriving signal from historical scorelines," the `team_form` mechanism
   almost certainly applies — that is not a reason to skip testing it, but it is a reason to expect
   a null result and to say so before running the test.
2. **Check the provisionally promoted section** before treating a live candidate as either fully
   established or non-existent — and if independent data becomes available for any reason, that is
   the occasion to attempt the confirmation check described there, not something to defer
   indefinitely.
3. **Check the open-hypotheses section** before re-deriving a question that's already
   mid-investigation — extend that thread rather than starting a parallel one.
4. **Check the deprioritized section** for ideas already reasoned away, so the reasoning gets
   engaged with directly rather than the idea being re-proposed as if novel.
5. **Use the methodology section** as the evaluation checklist for any new experiment — pre-register
   a primary endpoint, check leakage and coverage explicitly, judge results against observed noise
   rather than an invented threshold, treat any segmented breakdown as hypothesis-generating only,
   and use the four-tier classification (rejected / provisionally promoted / promoted / not
   confirmed) rather than forcing a result into the wrong bucket for convenience.

This document should be **read before ROADMAP.md's next milestone is scoped**, not just after it
runs — its job is to keep new work honest about what's already known, not to catalog results after
the fact.
