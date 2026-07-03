"""Odds mathematics: implied probabilities, overround, de-vig methods.

Pure functions, no pandas/DB dependencies. De-vig methods live in a registry
so new methods plug in without touching the rest of the pipeline:

    @register_devig("mymethod")
    def _mymethod(implied: Sequence[float]) -> List[float]: ...

Methods receive raw implied probabilities (1/odds, summing to 1 + margin)
and must return a proper distribution (sums to 1).

Why three methods (backtester arbitrates empirically):
- proportional: uniform margin removal; the common reference, but biased
  under favourite-longshot bias (books load more margin on longshots).
- power: solves sum(pi^k) = 1; shifts probability toward favourites.
- shin: models margin as insider-trading protection (Shin 1992/1993);
  typically best-calibrated for 1X2 in the literature.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Sequence

DevigFn = Callable[[Sequence[float]], List[float]]

_DEVIG_REGISTRY: Dict[str, DevigFn] = {}

_EPS = 1e-12


def register_devig(name: str) -> Callable[[DevigFn], DevigFn]:
    def deco(fn: DevigFn) -> DevigFn:
        if name in _DEVIG_REGISTRY:
            raise ValueError(f"de-vig method {name!r} already registered")
        _DEVIG_REGISTRY[name] = fn
        return fn
    return deco


def devig_methods() -> List[str]:
    return sorted(_DEVIG_REGISTRY)


def implied_probabilities(odds: Sequence[float]) -> List[float]:
    if any(o is None or o < 1.0 for o in odds):
        raise ValueError(f"invalid decimal odds: {odds}")
    return [1.0 / o for o in odds]


def overround(implied: Sequence[float]) -> float:
    """Booksum minus 1 (e.g. 0.05 == 5% margin)."""
    return sum(implied) - 1.0


def devig(implied: Sequence[float], method: str = "shin") -> List[float]:
    """Remove the margin from raw implied probabilities."""
    if method not in _DEVIG_REGISTRY:
        raise KeyError(f"unknown de-vig method {method!r}; have {devig_methods()}")
    if any(p <= 0 for p in implied):
        raise ValueError(f"implied probabilities must be positive: {implied}")
    probs = _DEVIG_REGISTRY[method](list(implied))
    total = sum(probs)
    if not math.isclose(total, 1.0, abs_tol=1e-6):
        raise AssertionError(f"de-vig {method!r} returned sum {total}")
    # exact renormalization of numerical residue
    return [p / total for p in probs]


def devig_odds(odds: Sequence[float], method: str = "shin") -> List[float]:
    return devig(implied_probabilities(odds), method)


# --------------------------------------------------------------------------
# built-in methods
# --------------------------------------------------------------------------

@register_devig("proportional")
def _proportional(implied: Sequence[float]) -> List[float]:
    s = sum(implied)
    return [p / s for p in implied]


@register_devig("power")
def _power(implied: Sequence[float]) -> List[float]:
    """Find k such that sum(pi^k) == 1 (k > 1 when margin > 0)."""
    s = sum(implied)
    if math.isclose(s, 1.0, abs_tol=1e-9):
        return list(implied)

    def f(k: float) -> float:
        return sum(p ** k for p in implied) - 1.0

    lo, hi = (1.0, 10.0) if s > 1.0 else (0.05, 1.0)
    return [p ** _bisect(f, lo, hi) for p in implied]


@register_devig("shin")
def _shin(implied: Sequence[float]) -> List[float]:
    """Shin's method. Solves for the insider fraction z such that the
    implied Shin probabilities sum to 1:

        p_i(z) = (sqrt(z^2 + 4(1-z) * pi_i^2 / s) - z) / (2(1-z))

    where s = sum(pi). z -> 0 as margin -> 0 (no-margin passthrough).
    """
    s = sum(implied)
    if s <= 1.0 + 1e-9:
        return _proportional(implied)

    def probs_for(z: float) -> List[float]:
        return [
            (math.sqrt(z * z + 4.0 * (1.0 - z) * (p * p) / s) - z) / (2.0 * (1.0 - z))
            for p in implied
        ]

    def f(z: float) -> float:
        return sum(probs_for(z)) - 1.0

    # f(0) = sqrt(s) - 1 > 0 and f is decreasing in z on (0, 1)
    z = _bisect(f, 0.0, 0.999)
    return probs_for(z)


def _bisect(f: Callable[[float], float], lo: float, hi: float,
            tol: float = 1e-12, max_iter: int = 200) -> float:
    flo, fhi = f(lo), f(hi)
    if flo == 0.0:
        return lo
    if fhi == 0.0:
        return hi
    if flo * fhi > 0:
        raise ValueError(f"bisection bracket does not straddle a root: "
                         f"f({lo})={flo}, f({hi})={fhi}")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < tol or (hi - lo) < tol:
            return mid
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)
