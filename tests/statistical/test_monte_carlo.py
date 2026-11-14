"""Ground-truth Monte Carlo checks. Fixed seeds; tolerances are set in simulation.py."""

import pytest

from ab_testing_copilot import simulation as sim
from ab_testing_copilot.experiment import ExperimentConfig, MetricSpec, analyze_experiment
from ab_testing_copilot.models import Decision

N = 4000


def test_validation_suite_all_pass():
    results = sim.run_validation_suite(n_sims=N, seed=123)
    failed = [r.name for r in results if r.passed is False]
    assert not failed, failed
    assert len(results) == 16


@pytest.mark.parametrize("dist", ["normal", "binary", "lognormal"])
def test_false_positive_rate_within_binomial_error(dist):
    r = sim.simulate_false_positive_rate(dist, n_sims=N, seed=11)
    assert abs(r.estimate - 0.05) < 4 * r.mc_standard_error + 0.005


def test_uncorrected_peeking_inflates_and_bonferroni_controls():
    naive = sim.simulate_peeking(n_looks=10, n_sims=2000, seed=5)
    fixed = sim.simulate_peeking(n_looks=10, correct=True, n_sims=2000, seed=5)
    assert naive.estimate > 0.12  # theory for 10 looks is roughly 0.19
    assert fixed.estimate <= 0.05 and fixed.passed


def test_cuped_power_gain_and_coverage():
    r = sim.simulate_cuped(rho=0.8, effect=0.1, n_sims=1500, seed=9)
    assert r.passed
    assert r.details["power_cuped"] > r.details["power_raw"] + 0.15
    assert abs(r.details["bias_cuped"]) < 0.01
    assert 0.93 <= r.details["coverage_cuped"] <= 0.97


def test_benjamini_hochberg_fwer_under_global_null():
    r = sim.simulate_multiple_testing(10, "benjamini-hochberg", n_sims=1500, seed=3)
    assert r.passed  # under the global null FDR == FWER


def test_small_sample_binary_is_reported_honestly():
    # Wald interval under-covers for rare events with small n: the check is expected to
    # be worse than nominal, and the scalar API warns in exactly this regime.
    r = sim.simulate_coverage(0.0, "binary", n_control=50, n_treatment=50, baseline=0.03,
                              n_sims=N, seed=2)
    assert r.estimate < 0.95 or r.estimate > 0.96


def test_decision_engine_error_rates_on_ground_truth(make_df):
    cfg = ExperimentConfig(primary=MetricSpec(column="converted", type="binary"))
    null = [analyze_experiment(make_df(n=4000, lift=0.0, seed=s), cfg).decision
            for s in range(200)]
    wrong = sum(d is not Decision.INCONCLUSIVE for d in null) / 200
    assert wrong <= 0.05 + 4 * (0.05 * 0.95 / 200) ** 0.5
    pos = [analyze_experiment(make_df(n=8000, lift=0.03, seed=s), cfg).decision
           for s in range(100)]
    assert sum(d is Decision.SHIP for d in pos) >= 90  # design power ~ 0.99
    assert not any(d is Decision.DO_NOT_SHIP for d in pos)


@pytest.mark.parametrize("kwargs", [{"n_sims": 10}, {"n_control": 1}])
def test_simulation_input_validation(kwargs):
    with pytest.raises(ValueError):
        sim.simulate_false_positive_rate(**kwargs)
    with pytest.raises(ValueError):
        sim.simulate_cuped(rho=1.0)
    with pytest.raises(ValueError):
        sim.simulate_peeking(n_per_arm=4, n_looks=5)
    with pytest.raises(ValueError):
        sim.simulate_power(0.95, "binary")
    with pytest.raises(ValueError):
        sim.simulate_multiple_testing(0)
