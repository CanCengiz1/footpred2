"""Evidence-tier registry -- the mapping from a research finding's
classification in docs/RESEARCH_RETROSPECTIVE.md to how much it is allowed
to influence the canonical FootPred prediction (see docs/VISION.md, "The
canonical FootPred prediction"). Weights are fixed and pre-registered,
deliberately not a continuous confidence-derived formula -- adopting one now,
before it has itself been validated to produce better-calibrated predictions
than the fixed-tier version, would be the same "intuition before implementation"
mistake the feature-engineering discipline exists to prevent, one level up.

A finding with zero weight (rejected / not_confirmed) never enters the
canonical blend at all -- ``is_live`` filters it out entirely rather than
multiplying its effect by zero, so a bug elsewhere can never let a rejected
finding leak a nonzero effect into a prediction.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

REGISTRY_PATH = Path("configs/findings_registry.json")

TIER_WEIGHTS = {
    "rejected": 0.0,
    "not_confirmed": 0.0,
    "provisionally_promoted": 0.25,
    "promoted": 1.0,
}


@dataclass(frozen=True)
class Finding:
    """One entry in the findings registry.

    ``extra_columns`` names the exact engineered column(s) this finding's
    model consumes on top of ``odds_core`` -- the same allowlist convention
    ``TabularPredictor`` already enforces, just sourced from config instead
    of hardcoded per caller. ``market`` scopes the finding to the one market
    it was actually validated on -- a finding proven on 1x2 never silently
    applies to btts or any other market it was never tested against.
    """
    finding_id: str
    tier: str
    market: str
    extra_columns: List[str]
    description: str
    retrospective_anchor: str

    @property
    def weight(self) -> float:
        if self.tier not in TIER_WEIGHTS:
            raise KeyError(f"unknown evidence tier {self.tier!r}; have {sorted(TIER_WEIGHTS)}")
        return TIER_WEIGHTS[self.tier]

    @property
    def is_live(self) -> bool:
        return self.weight > 0.0


def load_registry(path: Path | str = REGISTRY_PATH) -> List[Finding]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Finding(**entry) for entry in data["findings"]]


def live_findings(findings: Sequence[Finding], market: str) -> List[Finding]:
    """Findings that actually influence the canonical prediction for this
    market: nonzero weight AND scoped to this exact market."""
    return [f for f in findings if f.is_live and f.market == market]


def promoted_only(findings: Sequence[Finding], market: str) -> List[Finding]:
    """The subset used for the internal promoted-only counterfactual (see
    docs/VISION.md): live findings at full (promoted-tier) strength only,
    excluding anything still provisional."""
    return [f for f in live_findings(findings, market) if f.tier == "promoted"]
