"""Cross-checks against statsmodels. Skipped when statsmodels is not installed; CI installs it."""

import math

import numpy as np
import pytest

from ab_testing_copilot import analysis as an
from ab_testing_copilot import design

multitest = pytest.importorskip("statsmodels.stats.multitest")
power = pytest.importorskip("statsmodels.stats.power")
proportion = pytest.importorskip("statsmodels.stats.proportion")
weightstats = pytest.importorskip("statsmodels.stats.weightstats")


def test_two_proportion_z_test_matches_statsmodels():
    z, p = proportion.proportions_ztest(np.array([560, 480]), np.array([5000, 5000]))
    e = an.compare_proportions(480, 5000, 560, 5000)
    assert e.statistic == pytest.approx(z, rel=1e-10)
    assert e.p_value == pytest.approx(p, rel=1e-10)


def test_welch_matches_statsmodels():
    rng = np.random.default_rng(42)
    c, t = rng.normal(10, 2, 400), rng.normal(10.4, 5, 250)
    stat, p, _ = weightstats.ttest_ind(t, c, usevar="unequal")
    e = an.compare_means(c, t)
    assert e.statistic == pytest.approx(stat, rel=1e-10)
    assert e.p_value == pytest.approx(p, rel=1e-9)


@pytest.mark.parametrize(
    "ours, theirs",
    [("bonferroni", "bonferroni"), ("holm", "holm"), ("benjamini-hochberg", "fdr_bh")],
)
def test_pvalue_adjustments_match_statsmodels(ours, theirs):
    p = [0.001, 0.04, 0.03, 0.005, 0.2, 0.049, 0.8]
    expected = multitest.multipletests(p, method=theirs)[1]
    assert an.adjust_pvalues(p, ours) == pytest.approx(list(expected), rel=1e-12)


@pytest.mark.parametrize("ratio", [1.0, 3.0, 0.5])
def test_means_sample_size_and_power_match_statsmodels(ratio):
    std_dev, mde = 10.0, 1.0
    solver = power.NormalIndPower()
    n1 = solver.solve_power(effect_size=mde / std_dev, alpha=0.05, power=0.8, ratio=ratio)
    ours = design.sample_size_for_means(std_dev, mde, allocation_ratio=ratio)
    assert ours.n_control == math.ceil(n1)
    theirs = solver.power(effect_size=mde / std_dev, nobs1=800, alpha=0.05, ratio=ratio)
    assert design.power_for_means(std_dev, mde, 800, round(800 * ratio)) == pytest.approx(
        theirs, rel=1e-9
    )
