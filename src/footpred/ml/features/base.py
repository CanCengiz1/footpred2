"""Feature framework: versioned, registry-based feature groups.

Adding a feature family (team form, Elo, xG, injuries...) means writing one
class and registering it — DatasetBuilder never changes (Sprint-2 review
point 4). Every group carries a version; both are recorded in the dataset
manifest so feature changes can never silently invalidate old datasets or
backtests (point 7).

Contract: build(ctx) returns a DataFrame indexed by match_id containing only
this group's columns. Groups must be deterministic and use ONLY information
available before kickoff (as-of discipline; enforced by review + tests for
each group).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Protocol

import pandas as pd


@dataclass
class FeatureContext:
    """Everything a feature group may read. Sprint 2: the flat completed-
    matches frame. Sprint 3 extends this with historical as-of views —
    extending the context is additive and breaks no existing group."""
    matches: pd.DataFrame


class FeatureGroup(Protocol):
    name: str
    version: str

    def build(self, ctx: FeatureContext) -> pd.DataFrame: ...


_REGISTRY: Dict[str, FeatureGroup] = {}


def register_feature_group(group: FeatureGroup) -> FeatureGroup:
    if group.name in _REGISTRY:
        raise ValueError(f"feature group {group.name!r} already registered")
    _REGISTRY[group.name] = group
    return group


def get_feature_group(name: str) -> FeatureGroup:
    if name not in _REGISTRY:
        raise KeyError(f"unknown feature group {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def available_feature_groups() -> List[str]:
    return sorted(_REGISTRY)
