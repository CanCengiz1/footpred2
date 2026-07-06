# FootPred — Product Vision

## Purpose and scope

`ROADMAP.md` tracks future milestones and execution. `docs/RESEARCH_RETROSPECTIVE.md` is the
project's research memory — what's been learned and why it's believed. This document answers a
different question: **what is FootPred for, who is it for, and how do the research engine and the
product built on top of it stay honest with each other as both grow.**

This vision was written after a deliberate critical session stress-testing the product direction
with the same rigor the project applies to a research hypothesis — including the version of the
vision that didn't survive that scrutiny. It should be read alongside the retrospective, not
instead of it: every product claim below is scoped to what the retrospective actually supports
today, not to what would be convenient.

**Update policy** (mirrors the retrospective's): this document changes when a stage completes, a
validation criterion resolves, or a structural design decision changes — not after every sprint.

---

## Where this starts from

The honest current state, as of the retrospective's Core Finding:

- **Five independently designed tests of scoreline-derived signal have all failed or added no
  value over de-vigged market odds** (team-specific home/away split, halftime resilience,
  `team_form`, Dixon-Coles as a standalone model, draw-tendency residual). The category is formally
  closed.
- **The de-vigged market baseline (B0) is undefeated.** Every model built so far — Dixon-Coles,
  TabularPredictor with every feature tried — loses to it on every metric, every fold.
- **No finding is currently provisionally promoted or promoted.** Cross-market coherence → 1x2, the
  one candidate that had reached provisional status, was reclassified **not confirmed** on
  2026-07-06 after independent replication against the newly imported 2025/26 season failed to
  reproduce the effect. The canonical prediction currently reduces to the de-vigged market baseline
  alone (B0) — no live evidence-tier finding is contributing weight.
- **There are no users and no product surface today** beyond a local Streamlit research console
  used to build datasets and run backtests.

Any vision that implicitly assumes an edge already exists, or that transparency alone is a
sufficient value proposition, does not survive contact with this list. This one is built to not
require either.

---

## Thesis: one engine, two layers, not two competing visions

**The research sandbox is the engine.** It's where hypotheses are generated, pre-registered,
tested, rejected, or promoted, under the evidence discipline documented in the retrospective.

**The public workspace is the interface built on top of it.** Most users will never care about
Stage 0 existence tests or C-grid robustness sweeps. What they'll see is: one prediction, a
transparent account of how it was built, an evidence level for every input that shaped it, and a
publicly auditable track record.

Research produces the knowledge; the product is what makes that knowledge useful to someone who
isn't the person who built it. Neither layer is allowed to compromise the other: the product never
gets to show something research hasn't earned, and research is never allowed to stay purely
internal forever — the whole point of this document is committing to the second half of that.

---

## The canonical FootPred prediction

FootPred shows **one number per match**, not a market line and a separate model adjustment for the
user to reconcile themselves. That number is constructed as:

```
canonical prediction = promoted baseline + Σ (evidence-tier weight × provisionally-promoted finding's contribution)
```

**Evidence tier determines influence on that one number, not just whether something is visible:**

| Tier | Weight | What the user sees |
|---|---|---|
| Rejected / not confirmed | 0 | No influence on the prediction. Appears only in the static, dated closed-investigations ledger — claim, method, result, why it's settled. |
| Provisionally promoted | 0.25 (fixed, pre-registered) | Contributes to the canonical number at a fixed, conservative discount. The "why" panel names it explicitly as experimental and links to its caveats (fold disagreement, effect size vs. noise band, restricted evaluation population). |
| Promoted | 1.0 | Contributes at full strength, no experimental label needed. |

**Today, the promoted baseline is the de-vigged market probability** — nothing else has earned
promotion yet. That is stated to the user as fact, not hedged: FootPred's default position is the
best available honest number, plus a fully public account of everything tried to beat it and
failed, plus whatever is currently being tested live. That is a distinct, defensible claim on day
one with zero proven edge, precisely because it doesn't pretend otherwise.

**This is a starting point, not FootPred's long-term identity.** Today the formula above
degenerates to `canonical prediction = market baseline`, because both the "promoted" and
"provisionally promoted" sets are empty — the one candidate that had reached provisional status
(cross-market coherence → 1x2) was reclassified not confirmed on 2026-07-06 (see
`docs/RESEARCH_RETROSPECTIVE.md`). As research matures, the intent is for it to become a genuine
three-term prediction:

```
FootPred Prediction = Market Baseline + Confirmed Signals + Weighted Experimental Signals
```

where the market is the **anchor** the prediction is built on, not the product itself — the
product is what FootPred's own accumulated, evidence-gated research adds on top of it. This
doesn't change anything being built right now; the mechanism (fixed tier weights, logged
counterfactual, promotion only via independent replication) is identical whether the "Confirmed
Signals" term currently holds zero findings or several. It's recorded here so the market-only
starting state is never mistaken for the goal.

**Weights are fixed and pre-registered, not a continuous formula, deliberately.** A
confidence-derived continuous shrinkage function (e.g., weighting by a finding's own
effect-to-noise ratio) is a real future direction, but adopting it now — before it has itself been
validated to produce better-calibrated predictions than the fixed-tier version — would be exactly
the "intuition before evidence" mistake the feature-engineering discipline exists to prevent, one
level up. Fixed 0 / 0.25 / 1.0 first; a continuous version is its own future research question with
its own existence test, not an assumption baked in at design time.

**Internally, the promoted-only baseline is always computed and logged alongside the canonical
prediction, even though only the canonical number reaches the user.** This is not optional
infrastructure — it's what keeps the confirmation mechanism below honest. Without it, a good or bad
track record for the blended number can't be attributed to the experimental component at all.

---

## The bidirectional loop, made concrete

The relationship between research and product only means something if both directions are real,
not just the direction that already has a year of evidence behind it.

**Research → product: proven.** The entire retrospective is this arrow working — every ablation,
every rejection, every audited bug feeds directly into what the canonical prediction is or isn't
allowed to include.

**Product → research: currently a hypothesis, not yet a demonstrated mechanism. Two concrete,
falsifiable channels are what would prove it:**

1. **Production usage as replication data.** Every forward prediction a provisionally promoted
   finding makes in production is new, out-of-sample data that played no role in originally
   discovering the signal — exactly the independence the methodology already requires to promote a
   finding from provisional to promoted. The isolated contribution (canonical minus the logged
   promoted-only baseline, compared against realized outcomes) is what gets re-tested, not the
   canonical prediction's overall track record — the same ablation discipline used today, running
   quietly behind one user-facing number instead of being the whole analysis.
2. **User-originated hypotheses reaching a pre-registered Stage 0 test.** If a question a user
   raises ever gets scoped and run as a real Stage 0 test — pass or fail — that is the second arrow
   working. Zero instances after a defined observation window is itself a valid, honest finding: it
   would mean this channel doesn't work yet, not that the vision failed.

Both channels are designed to be checked, not assumed. See validation criteria below.

---

## The staged journey

1. **Engine** — the evidence-driven research framework and its findings. Largely built; ongoing by
   nature (research doesn't finish).
2. **Workspace** — build the evidence-exposure gate, the canonical-prediction mechanism, and the
   public ledger described above.
3. **Validate** — observe the pre-registered criteria below against real usage before drawing any
   conclusion about whether the workspace creates value beyond the research it's built on.
4. **Monetize / scale** — explicitly out of scope for this document. Deciding how (or whether) to
   monetize before stage 3 resolves would be the product equivalent of promoting a feature before
   its Stage 2 ablation — this vision does not do that.

No stage is assumed to succeed. A failure at stage 3 is a legitimate, informative outcome, not a
reason to quietly redefine "validated."

---

## Pre-registered validation criteria

Named now, deliberately, so "users find this valuable" can't be redefined after the fact to match
whatever happens. Structure is fixed here; **exact numeric thresholds are pre-registered
immediately before the workspace launches, against real baseline variance, not invented now with no
usage data to anchor them** — the same reason the research methodology dropped a fixed log-loss
threshold in favor of judging effect sizes against observed noise. Inventing a specific percentage
today would be exactly that mistake one level up.

1. **Return engagement, not first-visit traffic.** A defined fraction of a given week's visitors
   still returning several matchdays later. Proves the ledger format itself creates a reason to come
   back, not just one-time curiosity.
2. **Depth into the "why," not just the number.** Measurable engagement with the evidence panel
   behind a prediction. If nobody opens it, transparency is decoration for the builders, not value
   for users — a real possible outcome this criterion is designed to catch, not paper over.
3. **At least one user-originated question reaches a pre-registered Stage 0 test**, within a defined
   observation window. Tests whether the product → research arrow is real.
4. **Enough forward volume for at least one genuine confirmation test** of a provisionally promoted
   finding. If production usage never accumulates enough out-of-sample matches to rerun that test,
   the promotion-via-production mechanism doesn't work in practice, independent of whether the
   finding itself is real.

None of these are revenue signals — deliberately, per the staged sequence above.

---

## Reproducibility as standing discipline

Every milestone going forward gets a reproducible package: dataset snapshot, manifest, analysis
script, and results, so any published claim — in the retrospective or in the public ledger — can be
regenerated later, not just re-described. The infrastructure already exists (`DatasetBuilder`,
`save_dataset`, `content_hash`) but is currently only wired into the Evaluation UI's optional
persist path, unused by the actual research call sites that produced every milestone in the
retrospective. This stops being optional infrastructure and becomes required practice on the
research path itself, starting now — a gap that was found and should be closed before the ledger
above is asking the public to trust numbers that can't be regenerated.

---

## Explicit non-goals

Stated plainly so scope doesn't quietly drift under future pressure:

- **Not claiming an edge that doesn't exist.** The canonical prediction is the market baseline until
  something genuinely earns promotion. No amount of product polish changes that.
- **Not a tipster service.** No picks framed as confident advice beyond what the evidence tier of
  their inputs actually supports.
- **Not adopting a continuous shrinkage formula before it has its own evidence.** Fixed 0/0.25/1.0
  weights until a more sophisticated scheme is itself validated to help.
- **Not designing monetization yet.** That's stage 4, gated on stage 3 actually resolving.
- **Not skipping the evidence gate for expedience** — under user demand, competitive pressure, or
  any other future incentive to make the number look better than the evidence supports.
