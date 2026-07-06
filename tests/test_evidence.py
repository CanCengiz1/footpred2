import json

import pytest

from footpred.ml.evidence import (
    Finding, TIER_WEIGHTS, live_findings, load_registry, promoted_only,
)


def _finding(finding_id="f1", tier="provisionally_promoted", market="1x2"):
    return Finding(finding_id=finding_id, tier=tier, market=market,
                   extra_columns=["x"], description="d", retrospective_anchor="a")


# --------------------------- tier weights ----------------------------- #

def test_tier_weights_fixed_table():
    assert TIER_WEIGHTS == {
        "rejected": 0.0, "not_confirmed": 0.0,
        "provisionally_promoted": 0.25, "promoted": 1.0,
    }


def test_rejected_and_not_confirmed_are_not_live():
    assert not _finding(tier="rejected").is_live
    assert not _finding(tier="not_confirmed").is_live


def test_provisionally_promoted_and_promoted_are_live():
    assert _finding(tier="provisionally_promoted").is_live
    assert _finding(tier="promoted").is_live


def test_unknown_tier_raises():
    f = _finding(tier="not_a_real_tier")
    with pytest.raises(KeyError, match="unknown evidence tier"):
        _ = f.weight


# --------------------------- registry loading -------------------------- #

def test_load_registry_from_real_config_file():
    findings = load_registry()
    assert any(f.finding_id == "coherence_1x2" for f in findings)
    coherence = next(f for f in findings if f.finding_id == "coherence_1x2")
    # not_confirmed since 2026-07-06: independent replication against the
    # newly imported 2025/26 season failed to reproduce the effect (see
    # docs/RESEARCH_RETROSPECTIVE.md, "Not confirmed findings").
    assert coherence.tier == "not_confirmed"
    assert coherence.market == "1x2"
    assert coherence.extra_columns == ["incoherence_ou25"]
    assert coherence.is_live is False


def test_load_registry_from_tmp_file(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"findings": [
        {"finding_id": "f1", "tier": "promoted", "market": "ou_2.5",
         "extra_columns": ["a", "b"], "description": "d", "retrospective_anchor": "x"},
    ]}), encoding="utf-8")
    findings = load_registry(path)
    assert len(findings) == 1
    assert findings[0].finding_id == "f1"
    assert findings[0].extra_columns == ["a", "b"]


# --------------------------- live_findings / promoted_only -------------- #

def test_live_findings_excludes_zero_weight_and_wrong_market():
    findings = [
        _finding("rejected_one", tier="rejected", market="1x2"),
        _finding("provisional_1x2", tier="provisionally_promoted", market="1x2"),
        _finding("promoted_ou", tier="promoted", market="ou_2.5"),
    ]
    live = live_findings(findings, "1x2")
    assert [f.finding_id for f in live] == ["provisional_1x2"]


def test_promoted_only_excludes_provisional():
    findings = [
        _finding("provisional_1x2", tier="provisionally_promoted", market="1x2"),
        _finding("promoted_1x2", tier="promoted", market="1x2"),
    ]
    result = promoted_only(findings, "1x2")
    assert [f.finding_id for f in result] == ["promoted_1x2"]


def test_promoted_only_empty_when_nothing_promoted_yet():
    """Today's actual state: coherence_1x2 is not_confirmed (reclassified
    2026-07-06), so both the promoted and provisionally-promoted sets are
    empty -- the degenerate case docs/VISION.md describes."""
    findings = load_registry()
    assert promoted_only(findings, "1x2") == []
    assert live_findings(findings, "1x2") == []
