"""Group-sequential boundaries against published values and independent computations.

Published sources used below:
* Stata [ADAPT] ``gsbounds`` manual entry, examples 7-9 (one-sided 0.025, which gives the same
  critical values as a two-sided symmetric 0.05 design).
* NCSS PASS documentation, group-sequential tests, two-sided 0.05 example (it states that the
  values "match those of Reboussin (1992) exactly").
* gsDesign technical manual (Anderson), chapter 8 "Spending functions".
* DeMets & Lan (1994), Jennison & Turnbull (2000) and Armitage, McPherson & Rowe (1969) for
  the classical constants and the repeated-testing table.
"""

import math

import numpy as np
import pytest
from scipy.stats import multivariate_normal, norm

from ab_testing_copilot import design
from ab_testing_copilot import sequential as sq
from ab_testing_copilot.sequential import SequentialDesign

HALF_UNIT_4DP = 5e-5  # a value printed to four decimals is known to within half a unit
METHODS = ["obrien-fleming", "pocock"]


def _total(critical_values, fractions, drift=0.0):
    lower, upper = sq.exit_probabilities(critical_values, fractions, drift)
    return sum(lower) + sum(upper)


def test_obrien_fleming_five_looks_matches_stata_manual():
    b = sq.sequential_boundaries(5, 0.05, "obrien-fleming")
    assert b.critical_values == pytest.approx(
        [4.8769, 3.3570, 2.6803, 2.2898, 2.0310], abs=HALF_UNIT_4DP)
    assert b.cumulative_alpha[-1] == 0.05


def test_obrien_fleming_five_looks_matches_ncss_and_reboussin():
    # NCSS prints 3.3569 at the second look where Stata prints 3.3570. The converged value is
    # 3.357012 (see test_quadrature_has_converged), so this comparison allows one unit in the
    # last printed digit instead of half a unit.
    b = sq.sequential_boundaries(5, 0.05, "obrien-fleming")
    assert b.critical_values == pytest.approx(
        [4.8769, 3.3569, 2.6803, 2.2898, 2.0310], abs=1.5e-4)


def test_pocock_four_looks_matches_gsdesign_to_six_decimals():
    # gsDesign(k = 4, test.type = 2, sfu = sfLDPocock): alpha 0.025 in each tail.
    b = sq.sequential_boundaries(4, 0.05, "pocock")
    assert b.critical_values == pytest.approx(
        [2.368328, 2.367524, 2.358168, 2.350030], abs=1e-6)
    _, upper = sq.exit_probabilities(b.critical_values, b.information_fractions)
    assert list(np.cumsum(upper)) == pytest.approx(
        [0.00893435, 0.01550286, 0.02069972, 0.025], abs=1e-8)


def test_obrien_fleming_four_looks_matches_gsdesign():
    b = sq.sequential_boundaries(4, 0.05, "obrien-fleming")
    assert b.critical_values == pytest.approx([4.333, 2.963, 2.359, 2.014], abs=5e-4)


@pytest.mark.parametrize("fractions, published", [
    ([1 / 3, 2 / 3, 1.0], [3.1130, 2.4619, 2.0087]),
    ([1 / 3, 1 / 2, 2 / 3, 1.0], [3.1130, 2.7889, 2.5133, 2.0120]),
])
def test_integration_engine_matches_stata_for_a_third_spending_function(fractions, published):
    # Kim-DeMets spending alpha * t^3 (Stata gsbounds examples 8 and 9), equally and unequally
    # spaced looks. This checks the numerical engine independently of the two built-in functions.
    cumulative = [0.05 * t**3 for t in fractions]
    assert sq.boundaries_from_spending(cumulative, fractions) == pytest.approx(
        published, abs=HALF_UNIT_4DP)


def test_inflation_factor_matches_stata_information_ratio():
    # Stata prints "Info. ratio = 1.0247" for the five-look O'Brien-Fleming-style design at
    # its default power of 0.8.
    b = sq.sequential_boundaries(5, 0.05, "obrien-fleming")
    assert sq.inflation_factor(b, 0.8) == pytest.approx(1.0247, abs=HALF_UNIT_4DP)


@pytest.mark.parametrize("half_width, pocock, obrien_fleming", [
    (0.005, 2.41, 2.04),  # DeMets & Lan (1994), five looks, two-sided 0.05
    (0.0005, 2.413, 2.040),  # Jennison & Turnbull (2000), tables 2.1 and 2.3
])
def test_classical_constants_bracket_alpha(half_width, pocock, obrien_fleming):
    # A constant published to a given precision must bracket alpha = 0.05 exactly.
    t = sq.equal_fractions(5)

    def obf(c):
        return [c * math.sqrt(5 / k) for k in range(1, 6)]

    assert _total([pocock + half_width] * 5, t) < 0.05 < _total([pocock - half_width] * 5, t)
    assert (_total(obf(obrien_fleming + half_width), t) < 0.05
            < _total(obf(obrien_fleming - half_width), t))


@pytest.mark.parametrize("ratio, constant, shape", [(1.229, 2.413, "pocock"),
                                                    (1.028, 2.040, "obrien-fleming")])
def test_classical_sample_size_ratios_give_the_stated_power(ratio, constant, shape):
    # Jennison & Turnbull (2000), tables 2.2 and 2.4: maximum-sample-size ratios for power 0.8.
    t = sq.equal_fractions(5)
    crit = ([constant] * 5 if shape == "pocock"
            else [constant * math.sqrt(5 / k) for k in range(1, 6)])
    drift = math.sqrt(ratio) * (norm.isf(0.025) + norm.isf(0.2))
    assert sq.sequential_power(crit, t, drift) == pytest.approx(0.8, abs=1e-3)


@pytest.mark.parametrize("looks, published", [
    (1, 0.050), (2, 0.083), (3, 0.107), (4, 0.126), (5, 0.142), (10, 0.193)])
def test_repeated_testing_at_a_fixed_level_matches_the_classic_table(looks, published):
    # Armitage, McPherson & Rowe (1969): overall error of repeating a 5% test on growing data.
    crit = [float(norm.isf(0.025))] * looks
    assert _total(crit, sq.equal_fractions(looks)) == pytest.approx(published, abs=5e-4)


@pytest.mark.parametrize("method", METHODS)
def test_boundaries_agree_with_multivariate_normal_integration(method):
    # Independent method: scipy's Genz integration of the joint normal over the stay region.
    b = sq.sequential_boundaries(4, 0.05, method)
    t, c = np.array(b.information_fractions), np.array(b.critical_values)
    cov = np.sqrt(np.minimum.outer(t, t) / np.maximum.outer(t, t))
    stay = multivariate_normal(mean=np.zeros(4), cov=cov, seed=0, abseps=1e-9, releps=1e-9,
                               maxpts=4_000_000).cdf(c, lower_limit=-c)
    assert 1 - stay == pytest.approx(0.05, abs=1e-5)


@pytest.mark.parametrize("method", METHODS)
def test_quadrature_has_converged(method):
    fractions = [0.1, 0.35, 0.4, 0.8, 1.0]
    b = sq.sequential_boundaries(alpha=0.05, method=method, information_fractions=fractions)
    fine = sq.boundaries_from_spending(b.cumulative_alpha, fractions, resolution=3)
    assert b.critical_values == pytest.approx(fine, abs=1e-9)
    assert _total(b.critical_values, fractions) == pytest.approx(0.05, abs=1e-10)


@pytest.mark.parametrize("method", METHODS)
def test_exit_probabilities_reproduce_the_spending_function(method):
    b = sq.sequential_boundaries(6, 0.05, method)
    lower, upper = sq.exit_probabilities(b.critical_values, b.information_fractions)
    assert lower == pytest.approx(upper, rel=1e-9)  # symmetric under the null
    spent = np.cumsum(np.array(lower) + np.array(upper))
    assert list(spent) == pytest.approx(b.cumulative_alpha, abs=1e-11)
    assert b.nominal_alpha == pytest.approx([2 * norm.sf(c) for c in b.critical_values])
    assert all(np.diff(b.cumulative_alpha) > 0)


def test_single_look_is_the_fixed_horizon_test():
    b = sq.sequential_boundaries(1, 0.05, "pocock")
    assert b.critical_values == pytest.approx([norm.isf(0.025)])
    assert sq.inflation_factor(b, 0.9) == pytest.approx(1.0, abs=1e-9)
    drift = 0.125 / math.sqrt(2 / 1000)
    assert sq.sequential_power(b.critical_values, [1.0], drift) == pytest.approx(
        design.power_for_means(1.0, 0.125, 1000, 1000), abs=1e-12)


def test_power_is_alpha_under_the_null_and_grows_with_the_effect():
    b = sq.sequential_boundaries(5, 0.05, "obrien-fleming")
    crit, t = b.critical_values, b.information_fractions
    powers = [sq.sequential_power(crit, t, d) for d in (0.0, 1.0, 2.0, 3.0, 5.0, 12.0)]
    assert powers[0] == pytest.approx(0.05, abs=1e-10)
    assert powers == sorted(powers) and powers[-1] == pytest.approx(1.0, abs=1e-9)
    assert sq.sequential_power(crit, t, -3.0) == pytest.approx(powers[3], rel=1e-9)
    drift = sq.required_drift(b, 0.9)
    assert sq.sequential_power(crit, t, drift) == pytest.approx(0.9, abs=1e-8)
    assert drift > sq.fixed_horizon_drift(0.05, 0.9)  # looking early costs some power
    with pytest.raises(ValueError):
        sq.required_drift(b, 0.01)
    with pytest.raises(ValueError):
        sq.fixed_horizon_drift(0.05, 1.0)


def test_expected_stopping_point():
    b = sq.sequential_boundaries(5, 0.05, "pocock")
    crit, t = b.critical_values, b.information_fractions
    under_null = sq.expected_information(crit, t, 0.0)
    assert 0.95 < under_null < 1.0  # stops early only on a false positive
    assert sq.expected_information(crit, t, 40.0) == pytest.approx(0.2, abs=1e-9)
    assert sq.expected_information(crit, t, 3.0) < under_null


@pytest.mark.parametrize("method", METHODS)
def test_spending_function_shape(method):
    assert sq.alpha_spent(1.0, 0.05, method) == 0.05
    assert sq.alpha_spent(3.0, 0.05, method) == 0.05
    values = [sq.alpha_spent(t, 0.05, method) for t in (0.01, 0.2, 0.5, 0.8, 0.999)]
    assert values == sorted(values) and values[0] >= 0 and values[-1] < 0.05


def test_spending_function_values():
    assert sq.alpha_spent(0.2, 0.05, "pocock") == pytest.approx(
        0.05 * math.log(1 + (math.e - 1) * 0.2), rel=1e-12)
    assert sq.alpha_spent(0.2, 0.05, "obrien-fleming") == pytest.approx(
        4 * norm.sf(norm.isf(0.0125) / math.sqrt(0.2)), rel=1e-12)
    # the O'Brien-Fleming type spends almost nothing early, the Pocock type spends evenly
    assert sq.alpha_spent(0.2, 0.05, "obrien-fleming") < 2e-6 < 0.014 < sq.alpha_spent(
        0.2, 0.05, "pocock")


@pytest.mark.parametrize("kwargs", [
    {"information_fraction": 0.5, "alpha": 0.0}, {"information_fraction": 0.5, "alpha": 1.0},
    {"information_fraction": 0.0}, {"information_fraction": -1.0},
    {"information_fraction": float("nan")}, {"information_fraction": 0.5, "method": "linear"},
])
def test_spending_function_rejects_bad_input(kwargs):
    with pytest.raises(ValueError):
        sq.alpha_spent(**kwargs)


@pytest.mark.parametrize("bad", [
    [], [0.5, 0.5, 1.0], [0.6, 0.5, 1.0], [0.0, 1.0], [-0.1, 1.0], [0.5, float("nan")],
    [0.5, float("inf")], [0.5, 0.5005, 1.0], [i / 101 for i in range(1, 102)],
])
def test_invalid_information_fractions_are_rejected(bad):
    with pytest.raises(ValueError):
        sq.boundaries_from_spending([0.01] * len(bad), bad)
    with pytest.raises(ValueError):
        sq.exit_probabilities([2.0] * len(bad), bad)


def test_other_invalid_inputs_are_rejected():
    t = [0.5, 1.0]
    for cumulative in ([0.03, 0.02], [0.02, 1.0], [-0.01, 0.05], [0.05], [0.01, float("nan")]):
        with pytest.raises(ValueError):
            sq.boundaries_from_spending(cumulative, t)
    for crit, drift, resolution in (([2.0], 0.0, 1), ([-1.0, 2.0], 0.0, 1),
                                    ([2.0, float("nan")], 0.0, 1),
                                    ([2.0, 2.0], float("inf"), 1), ([2.0, 2.0], 0.0, 0)):
        with pytest.raises(ValueError):
            sq.exit_probabilities(crit, t, drift, resolution)
    with pytest.raises(ValueError):
        sq.boundaries_from_spending([0.01, 0.05], t, resolution=0)
    with pytest.raises(ValueError):
        sq.sequential_boundaries()
    with pytest.raises(ValueError):
        sq.sequential_boundaries(information_fractions=[0.5, 0.9])
    with pytest.raises(ValueError):
        sq.sequential_boundaries(3, information_fractions=[0.5, 1.0])
    with pytest.raises(ValueError):
        sq.sequential_boundaries(3, alpha=1.2)
    for looks in (0, 101):
        with pytest.raises(ValueError):
            sq.equal_fractions(looks)


@pytest.mark.parametrize("method", METHODS)
def test_extreme_designs_stay_exact(method):
    many = sq.sequential_boundaries(100, 0.05, method)
    assert _total(many.critical_values, many.information_fractions) == pytest.approx(
        0.05, abs=1e-9)
    strict = sq.sequential_boundaries(3, 1e-8, method)
    assert _total(strict.critical_values, strict.information_fractions) == pytest.approx(
        1e-8, rel=1e-6)
    loose = sq.sequential_boundaries(3, 0.9, method)
    assert _total(loose.critical_values, loose.information_fractions) == pytest.approx(
        0.9, abs=1e-9)
    assert all(c > 0 for c in loose.critical_values)


def test_a_look_that_cannot_spend_alpha_gets_an_infinite_boundary():
    # At 0.1% of the information the O'Brien-Fleming-type function spends less than the
    # smallest representable number: stopping is impossible there, later looks are unaffected.
    fractions = [0.001, 0.5, 1.0]
    b = sq.sequential_boundaries(alpha=0.05, method="obrien-fleming",
                                 information_fractions=fractions)
    assert math.isinf(b.critical_values[0]) and b.nominal_alpha[0] == 0.0
    assert _total(b.critical_values, fractions) == pytest.approx(0.05, abs=1e-9)
    two = sq.sequential_boundaries(alpha=0.05, method="obrien-fleming",
                                   information_fractions=[0.5, 1.0])
    assert b.critical_values[1:] == pytest.approx(two.critical_values, abs=1e-9)


@pytest.mark.parametrize("kwargs", [
    {"planned_looks": 3, "current_look": 4}, {"planned_looks": 0, "current_look": 1},
    {"planned_looks": 3, "current_look": 0}, {"planned_looks": 101, "current_look": 1},
    {"planned_looks": 3, "current_look": 1, "information_fractions": [0.5, 1.0]},
    {"planned_looks": 2, "current_look": 1, "information_fractions": [0.5, 0.9]},
    {"planned_looks": 2, "current_look": 1, "information_fractions": [0.9, 0.5]},
    {"planned_looks": 2, "current_look": 1, "planned_sample_size": 1},
    {"planned_looks": 2, "current_look": 1, "surprise": True},
])
def test_design_validation(kwargs):
    with pytest.raises(ValueError):
        SequentialDesign(method="obrien-fleming", **kwargs)
    with pytest.raises(ValueError):
        SequentialDesign(method="haybittle-peto", planned_looks=2, current_look=1)


def test_look_uses_the_planned_fraction_when_no_sample_size_is_declared():
    d = SequentialDesign(method="obrien-fleming", planned_looks=5, current_look=2)
    look = sq.sequential_look(d, 0.05)
    assert look.critical_value == pytest.approx(3.3570, abs=HALF_UNIT_4DP)
    assert look.information_fraction == 0.4 and look.observed_fraction is None
    assert not look.is_final and not look.warnings
    assert any("not checked against the data" in n for n in look.notes)
    assert look.plan.critical_values == pytest.approx(
        [4.8769, 3.3570, 2.6803, 2.2898, 2.0310], abs=HALF_UNIT_4DP)
    custom = SequentialDesign(method="pocock", planned_looks=3, current_look=3,
                              information_fractions=[0.3, 0.6, 1.0])
    last = sq.sequential_look(custom, 0.05)
    assert last.is_final and last.cumulative_alpha == 0.05
    assert last.critical_value == pytest.approx(
        sq.sequential_boundaries(alpha=0.05, method="pocock",
                                 information_fractions=[0.3, 0.6, 1.0]).critical_values[-1])


def test_look_spends_alpha_for_the_information_actually_collected():
    d = SequentialDesign(method="obrien-fleming", planned_looks=5, current_look=2,
                         planned_sample_size=10_000)
    on_plan = sq.sequential_look(d, 0.05, 4000)
    assert on_plan.critical_value == pytest.approx(3.3570, abs=HALF_UNIT_4DP)
    assert on_plan.observed_fraction == 0.4 and not on_plan.notes
    late = sq.sequential_look(d, 0.05, 5500)
    spent = [sq.alpha_spent(t, 0.05, "obrien-fleming") for t in (0.2, 0.55)]
    assert late.critical_value == pytest.approx(
        sq.boundaries_from_spending(spent, [0.2, 0.55])[-1], abs=1e-12)
    assert late.critical_value < on_plan.critical_value  # more information, more alpha to spend
    assert late.information_fraction == 0.55 and late.cumulative_alpha == spent[-1]
    assert any("planned at 40.0%" in n for n in late.notes)


def test_final_look_spends_everything_and_flags_an_under_run():
    d = SequentialDesign(method="pocock", planned_looks=3, current_look=3,
                         planned_sample_size=9000)
    full = sq.sequential_look(d, 0.05, 9000)
    assert full.is_final and full.cumulative_alpha == 0.05 and not full.warnings
    planned = sq.sequential_boundaries(3, 0.05, "pocock").critical_values[-1]
    assert full.critical_value == pytest.approx(planned, abs=1e-12)
    short = sq.sequential_look(d, 0.05, 7000)
    assert short.cumulative_alpha == 0.05 and len(short.warnings) == 1
    spent = [sq.alpha_spent(1 / 3, 0.05, "pocock"), sq.alpha_spent(2 / 3, 0.05, "pocock"), 0.05]
    assert short.critical_value == pytest.approx(
        sq.boundaries_from_spending(spent, [1 / 3, 2 / 3, 7000 / 9000])[-1], abs=1e-12)
    assert short.critical_value != pytest.approx(planned, abs=1e-4)
    over = sq.sequential_look(d, 0.05, 12_000)
    assert not over.warnings and any("133.3%" in n for n in over.notes)


def test_reaching_the_planned_sample_early_makes_the_look_final():
    d = SequentialDesign(method="obrien-fleming", planned_looks=4, current_look=3,
                         planned_sample_size=8000)
    look = sq.sequential_look(d, 0.05, 8000)
    assert look.is_final and look.cumulative_alpha == 0.05
    assert any("treated as the final analysis" in n for n in look.notes)


def test_a_look_with_less_data_than_the_previous_one_is_refused():
    d = SequentialDesign(method="obrien-fleming", planned_looks=4, current_look=3,
                         planned_sample_size=8000)
    with pytest.raises(ValueError, match="not above"):
        sq.sequential_look(d, 0.05, 3000)  # 37.5% of the plan, but look 2 was planned at 50%
    with pytest.raises(ValueError):
        sq.sequential_look(d, 0.05, 0)
    with pytest.raises(ValueError):
        sq.sequential_look(d, 1.5, 7000)


def test_sequential_assumptions_drop_the_single_look_statement():
    binary = design.sample_size_for_proportions(0.1, 0.02).assumptions
    continuous = design.sample_size_for_means(10, 1).assumptions
    for fixed in (binary, continuous):
        merged = sq.sequential_assumptions(fixed)
        kept = merged[: -len(sq.ASSUMPTIONS)]
        assert not any("ixed-horizon" in a for a in kept)
        assert any(a.startswith("Independent units") for a in kept)
        assert merged[-len(sq.ASSUMPTIONS):] == list(sq.ASSUMPTIONS)
