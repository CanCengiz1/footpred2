"""Target (label) derivation from match scores. Pure functions.

Selection strings match odds selections exactly ("home"/"draw"/"away",
"over"/"under", "yes"/"no") so predictions, odds and targets align without
mapping tables. HT/FT uses the familiar bookmaker notation "1/X" etc. and is
None when half-time data is absent (per Sprint-0 answer #3: such rows still
serve standard markets).
"""
from __future__ import annotations

from typing import Optional

_SIGN = {1: "1", 0: "X", -1: "2"}


def label_1x2(ft_home: int, ft_away: int) -> str:
    return "home" if ft_home > ft_away else "away" if ft_away > ft_home else "draw"


def label_ou25(ft_home: int, ft_away: int) -> str:
    return "over" if ft_home + ft_away > 2.5 else "under"


def label_btts(ft_home: int, ft_away: int) -> str:
    return "yes" if ft_home > 0 and ft_away > 0 else "no"


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and v != v)  # NaN-aware


def label_htft(
    ht_home: Optional[int], ht_away: Optional[int], ft_home: int, ft_away: int
) -> Optional[str]:
    """9-class HT/FT in '1/X' notation; None when HT is unknown.

    NaN-aware: pandas frames carry missing HT as float NaN, and naive
    ``is None`` checks would let NaN comparisons fabricate 'X/X' labels."""
    if _missing(ht_home) or _missing(ht_away):
        return None
    ht_home, ht_away = int(ht_home), int(ht_away)  # type: ignore[arg-type]
    ht = _SIGN[(ht_home > ht_away) - (ht_home < ht_away)]
    ft = _SIGN[(ft_home > ft_away) - (ft_home < ft_away)]
    return f"{ht}/{ft}"


HTFT_CLASSES = ["1/1", "1/X", "1/2", "X/1", "X/X", "X/2", "2/1", "2/X", "2/2"]
