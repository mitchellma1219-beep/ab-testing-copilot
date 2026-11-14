"""Monte Carlo checks of the sequential, novelty, segment and ratio features.

Seeds are fixed. Every tolerance is 4 Monte Carlo standard errors plus the approximation
slack used throughout simulation.py (0.005 normal data, 0.01 binary data), and every power
threshold was derived from the design before the simulation was run.
"""

import math

import numpy as np
import pytest
from scipy.stats import norm

from ab_testing_copilot import heterogeneity as ht
from ab_testing_copilot import novelty as nv
from ab_testing_copilot import sequential as sq
from ab_testing_copilot import simulation as sim
from ab_testing_copilot.analysis import compare_proportions
from ab_testing_copilot.experiment import ExperimentConfig, MetricSpec, analyze_experiment
from ab_testing_copilot.models import Decision, PeriodEffect
from ab_testing_copilot.sequential import SequentialDesign
from ab_testing_copilot.synthetic import make_experiment

N = 4000


def _upper(rate, n, slack):
    return rate + 4 * math.sqrt(rate * (1 - rate) / n) + slack


@pytest.mark.parametrize("method", ["obrien-fleming", "pocock"])
@pytest.mark.parametrize("looks", [3, 8])
def test_sequential_type_one_error_is_alpha(method, looks):
    r = sim.simulate_sequential(method, looks, n_per_arm=1200, n_sims=N, seed=11)
    assert r.passed and r.expected == 0.05
    assert abs(r.estimate - 0.05) <= 4 * r.mc_standard_error + 0.005
    assert r.details["mean_stopping_fraction"] == pytest.approx(
        r.details["expected_stopping_fraction"], abs=0.01)


@pytest.mark.parametrize("method", ["obrien-fleming", "pocock"])
def test_sequential_power_matches_numerical_integration(method):
    r = sim.simulate_sequential(method, 4, n_per_arm=1000, effect=0.13, n_sims=N, seed=12)
    assert r.passed and 0.7 < r.expected < 0.85
    # stopping early saves sample when the effect is real
    assert r.details["mean_stopping_fraction"] < 0.9
    assert r.details["mean_stopping_fraction"] == pytest.approx(
        r.details["expected_stopping_fraction"], abs=0.02)


def test_sequential_binary_metric_and_alpha_other_than_five_percent():
    r = sim.simulate_sequential("pocock", 5, n_per_arm=5000, distribution="binary",
                                n_sims=N, seed=13)
    assert r.passed
    strict = sim.simulate_sequential("obrien-fleming", 4, alpha=0.01, n_sims=N, seed=14)
    assert strict.passed and strict.expected == 0.01
    power = sim.simulate_sequential("obrien-fleming", 4, n_per_arm=4000, effect=0.02,
                                    distribution="binary", n_sims=N, seed=15)
    assert power.passed


def test_uncorrected_repeated_testing_matches_the_integration_engine():
    # Two independent routes to the same number: Monte Carlo on accumulating data, and the
    # recursive integration with a constant critical value of 1.96.
    mc = sim.simulate_peeking(n_looks=5, correct=False, n_sims=N, seed=16)
    lower, upper = sq.exit_probabilities([float(norm.isf(0.025))] * 5, sq.equal_fractions(5))
    exact = sum(lower) + sum(upper)
    assert abs(mc.estimate - exact) <= 4 * math.sqrt(exact * (1 - exact) / N) + 0.005


def test_decision_engine_holds_alpha_across_the_looks_of_a_design():
    looks, n = 4, 2000
    cfg = ExperimentConfig(primary=MetricSpec(column="converted", type="binary"))
    wrong = 0
    for seed in range(250):
        df = make_experiment(n=n, lift=0.0, seed=1000 + seed)
        for k in range(1, looks + 1):
            design = SequentialDesign(method="obrien-fleming", planned_looks=looks,
                                      current_look=k, planned_sample_size=n)
            r = analyze_experiment(df.iloc[: n * k // looks],
                                   cfg.model_copy(update={"sequential": design}))
            if r.decision is not Decision.INCONCLUSIVE:
                wrong += 1
                break
    assert wrong / 250 <= _upper(0.05, 250, 0.01)


def test_decision_engine_stops_early_for_a_real_effect():
    looks, n = 4, 2000
    cfg = ExperimentConfig(primary=MetricSpec(column="converted", type="binary"))
    shipped, early, harmed = 0, 0, 0
    for seed in range(100):
        df = make_experiment(n=n, lift=0.05, seed=2000 + seed)
        for k in range(1, looks + 1):
            design = SequentialDesign(method="obrien-fleming", planned_looks=looks,
                                      current_look=k, planned_sample_size=n)
            r = analyze_experiment(df.iloc[: n * k // looks],
                                   cfg.model_copy(update={"sequential": design}))
            if r.decision is Decision.SHIP:
                shipped += 1
                early += k < looks
                break
            if r.decision is Decision.DO_NOT_SHIP:
                harmed += 1
                break
    # drift = 0.05 / 0.0148 = 3.4, design power about 0.91 for four O'Brien-Fleming looks
    assert shipped >= 80 and harmed == 0 and early >= 40


def _daily_effects(rng, lifts, n_per_arm, base=0.10):
    periods = []
    for day, lift in enumerate(lifts):
        xc, xt = rng.binomial(n_per_arm, base), rng.binomial(n_per_arm, base + lift)
        e = compare_proportions(int(xc), n_per_arm, int(xt), n_per_arm)
        periods.append(PeriodEffect(index=day, label=str(day), n_control=n_per_arm,
                                    n_treatment=n_per_arm, effect=e.absolute_effect,
                                    std_error=e.std_error))
    return periods


def test_novelty_check_rarely_fires_on_a_stable_effect():
    rng = np.random.default_rng(21)
    sims = 400
    results = [nv.assess_novelty(_daily_effects(rng, [0.02] * 14, 500)) for _ in range(sims)]
    decay = sum(r.decay_detected for r in results) / sims
    any_trend = sum(r.decay_detected or r.growth_detected or r.reversal_detected
                    for r in results) / sims
    assert any_trend <= _upper(0.05, sims, 0.01)  # two-sided trend test at 5%
    assert decay <= _upper(0.025, sims, 0.01)  # only one direction is a novelty warning


def test_novelty_check_detects_a_fast_decay():
    # lift 6 pp halving every 3 days, 2,000 units per arm per day: expected t about -5.
    rng = np.random.default_rng(22)
    lifts = [0.06 * 0.5 ** (d / 3) for d in range(14)]
    hits = sum(nv.assess_novelty(_daily_effects(rng, lifts, 2000)).decay_detected
               for _ in range(200))
    assert hits / 200 >= 0.9


def _segments(rng, lifts, n_per_arm=2000, base=0.10, correction="holm"):
    est, wide = {}, {}
    for i, lift in enumerate(lifts):
        xc, xt = int(rng.binomial(n_per_arm, base)), int(rng.binomial(n_per_arm, base + lift))
        est[f"s{i}"] = compare_proportions(xc, n_per_arm, xt, n_per_arm)
        wide[f"s{i}"] = compare_proportions(xc, n_per_arm, xt, n_per_arm, 0.05 / len(lifts))
    return ht.summarise_segments(est, wide, "segment", 0.05, correction)


@pytest.mark.parametrize("correction", ["holm", "bonferroni", "benjamini-hochberg"])
def test_segment_family_error_is_controlled_when_nothing_differs(correction):
    rng = np.random.default_rng(23)
    sims = 400
    runs = [_segments(rng, [0.0] * 5, correction=correction) for _ in range(sims)]
    any_flag = sum(any(s.significant_after_correction for s in r.segments) for r in runs) / sims
    assert any_flag <= _upper(0.05, sims, 0.01)
    covered = sum(all(s.simultaneous_ci_low <= 0 <= s.simultaneous_ci_high for s in r.segments)
                  for r in runs) / sims
    assert covered >= 0.95 - 4 * math.sqrt(0.05 * 0.95 / sims) - 0.01


def test_heterogeneity_test_is_calibrated_and_has_power():
    rng = np.random.default_rng(24)
    sims = 400
    same = sum(_segments(rng, [0.02] * 5).heterogeneity_detected for _ in range(sims)) / sims
    assert abs(same - 0.05) <= 4 * math.sqrt(0.05 * 0.95 / sims) + 0.01
    # one of five segments carries a 5 pp lift: non-centrality about 22 on 4 df
    differ = sum(_segments(rng, [0, 0, 0, 0, 0.05]).heterogeneity_detected
                 for _ in range(200)) / 200
    assert differ >= 0.9


def test_ratio_metric_delta_method_against_the_wrong_unit():
    delta = sim.simulate_ratio_metric("delta", n_sims=N, seed=25)
    rows = sim.simulate_ratio_metric("rows", n_sims=N, seed=25)
    assert delta.passed and rows.passed is None
    assert rows.estimate > delta.estimate + 0.05  # impressions treated as units over-reject
    cover = sim.simulate_ratio_metric("delta", effect=0.02, coverage=True, n_sims=N, seed=26)
    assert cover.passed
    assert sim.simulate_ratio_metric("rows", coverage=True, n_sims=500, seed=27).estimate < 0.93


@pytest.mark.parametrize("call", [
    lambda: sim.simulate_sequential(n_looks=0),
    lambda: sim.simulate_sequential(n_per_arm=4, n_looks=5),
    lambda: sim.simulate_sequential(distribution="lognormal"),  # type: ignore[arg-type]
    lambda: sim.simulate_sequential(distribution="binary", effect=0.95),
    lambda: sim.simulate_sequential(method="haybittle"),  # type: ignore[arg-type]
    lambda: sim.simulate_ratio_metric(analysis="bootstrap"),  # type: ignore[arg-type]
    lambda: sim.simulate_ratio_metric(effect=0.95),
    lambda: sim.simulate_ratio_metric(mean_rows=0.5),
    lambda: sim.simulate_ratio_metric(n_sims=10),
    lambda: sim.simulate_p_values(alpha=0),
    lambda: sim.simulate_p_values("poisson"),  # type: ignore[arg-type]
    lambda: sim.simulate_p_values(std_dev=0),
])
def test_new_simulations_validate_their_input(call):
    with pytest.raises(ValueError):
        call()


def test_simulated_p_values_are_uniform_without_an_effect():
    p, lo, hi = sim.simulate_p_values("normal", n_sims=N, seed=28)
    assert p.shape == lo.shape == hi.shape == (N,)
    hist = np.histogram(p, bins=10, range=(0, 1))[0] / N
    assert np.abs(hist - 0.1).max() <= 4 * math.sqrt(0.1 * 0.9 / N) + 0.005
    shifted, *_ = sim.simulate_p_values("binary", 5000, 5000, effect=0.02, n_sims=500, seed=29)
    assert (shifted < 0.05).mean() > 0.7
