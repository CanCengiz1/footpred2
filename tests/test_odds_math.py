import math


from footpred.ml.odds_math import (
    devig,
    devig_methods,
    devig_odds,
    implied_probabilities,
    overround,
    register_devig,
)

THREE_WAY = [1.90, 3.60, 4.20]      # typical 1X2, ~5.4% margin
TWO_WAY = [1.85, 1.95]              # typical O/U, ~5.3% margin
LONGSHOT = [1.30, 5.50, 11.00]      # heavy favourite + longshot


def test_implied_probabilities_basic():
    imp = implied_probabilities([2.0, 4.0, 4.0])
    assert imp == [0.5, 0.25, 0.25]
    assert math.isclose(overround(imp), 0.0, abs_tol=1e-12)


def test_overround_typical_1x2_in_plausible_band():
    m = overround(implied_probabilities(THREE_WAY))
    assert 0.02 <= m <= 0.15


def test_all_methods_sum_to_one_two_and_three_way():
    for method in devig_methods():
        for odds in (THREE_WAY, TWO_WAY, LONGSHOT):
            probs = devig_odds(odds, method)
            assert math.isclose(sum(probs), 1.0, abs_tol=1e-9), (method, odds)
            assert all(0.0 < p < 1.0 for p in probs), (method, odds)


def test_zero_margin_is_identity_for_all_methods():
    fair = [0.5, 0.3, 0.2]
    for method in devig_methods():
        out = devig(fair, method)
        assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(out, fair)), method


def test_order_preserved():
    for method in devig_methods():
        probs = devig_odds(LONGSHOT, method)
        assert probs[0] > probs[1] > probs[2], method


def test_power_and_shin_correct_longshot_bias_vs_proportional():
    """The bias correction: proportional keeps too much probability on the
    longshot; power and shin must assign it LESS and the favourite MORE."""
    prop = devig_odds(LONGSHOT, "proportional")
    for method in ("power", "shin"):
        adj = devig_odds(LONGSHOT, method)
        assert adj[-1] < prop[-1], method   # longshot down
        assert adj[0] > prop[0], method     # favourite up


def test_shin_known_direction_on_symmetric_market():
    # symmetric two-way: every sane method must return 50/50
    for method in devig_methods():
        probs = devig_odds([1.90, 1.90], method)
        assert math.isclose(probs[0], 0.5, abs_tol=1e-9), method


def test_registry_is_extensible_without_touching_pipeline():
    @register_devig("test_custom")
    def _custom(implied):
        s = sum(implied)
        return [p / s for p in implied]

    assert "test_custom" in devig_methods()
    probs = devig_odds(THREE_WAY, "test_custom")
    assert math.isclose(sum(probs), 1.0, abs_tol=1e-9)


def test_duplicate_registration_rejected():
    try:
        @register_devig("proportional")
        def _dup(implied):  # pragma: no cover
            return list(implied)
    except ValueError as e:
        assert "already registered" in str(e)
    else:
        raise AssertionError("duplicate registration must raise")


def test_invalid_inputs_raise():
    for bad in ([0.99, 2.0], [2.0, None]):
        try:
            implied_probabilities(bad)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad}")
    try:
        devig([0.5, 0.5], "no_such_method")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown method must raise KeyError")
