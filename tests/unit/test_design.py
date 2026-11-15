import math

import pytest
from scipy.stats import norm

from ab_testing_copilot import design


def test_proportion_sample_size_matches_textbook_value():
    # 10% -> 12%, alpha .05, power .8: 3,841 per arm (Fleiss / Evan Miller calculator).
    r = design.sample_size_for_proportions(0.10, 0.02)
    assert (r.n_control, r.n_treatment, r.n_total) == (3841, 3841, 7682)
    assert r.relative_mde == pytest.approx(0.2)


def test_means_sample_size_matches_closed_form():
    r = design.sample_size_for_means(std_dev=10, absolute_mde=1)
    z = norm.ppf(0.975) + norm.ppf(0.8)
    assert r.n_control == math.ceil(2 * z**2 * 100)  # 1570


def test_unequal_allocation_needs_more_total_sample():
    eq = design.sample_size_for_proportions(0.10, 0.02)
    uneq = design.sample_size_for_proportions(0.10, 0.02, allocation_ratio=3)
    assert uneq.n_total > eq.n_total
    assert uneq.n_treatment == pytest.approx(3 * uneq.n_control, abs=3)


def test_power_roundtrip_and_monotonicity():
    r = design.sample_size_for_proportions(0.10, 0.02)
    p = design.power_for_proportions(0.10, 0.02, r.n_control, r.n_treatment)
    assert 0.80 <= p < 0.801
    assert design.power_for_proportions(0.10, 0.02, 1000, 1000) < p
    assert design.power_for_means(1.0, 0.0, 100, 100) == pytest.approx(0.05)


def test_negative_mde_is_symmetric_for_means():
    assert (design.sample_size_for_means(5, -1).n_control
            == design.sample_size_for_means(5, 1).n_control)


def test_mde_inverts_sample_size():
    mde = design.mde_for_proportions(0.10, 3841, 3841)
    assert mde == pytest.approx(0.02, abs=2e-4)


def test_duration():
    assert design.duration_days(7682, 1000, 0.5) == 16
    with pytest.raises(ValueError):
        design.duration_days(100, 0)
    with pytest.raises(ValueError):
        design.duration_days(100, 10, 1.5)


@pytest.mark.parametrize("kwargs", [
    {"baseline": 0.0, "absolute_mde": 0.1}, {"baseline": 0.5, "absolute_mde": 0.0},
    {"baseline": 0.9, "absolute_mde": 0.2}, {"baseline": 0.1, "absolute_mde": 0.01, "alpha": 0},
    {"baseline": 0.1, "absolute_mde": 0.01, "power": 1.0},
    {"baseline": 0.1, "absolute_mde": 0.01, "allocation_ratio": 0},
])
def test_invalid_design_inputs(kwargs):
    with pytest.raises(ValueError):
        design.sample_size_for_proportions(**kwargs)


def test_invalid_means_inputs():
    with pytest.raises(ValueError):
        design.sample_size_for_means(0, 1)
    with pytest.raises(ValueError):
        design.sample_size_for_means(1, 0)
    with pytest.raises(ValueError):
        design.mde_for_proportions(0.5, 2, 2, power=0.999)
