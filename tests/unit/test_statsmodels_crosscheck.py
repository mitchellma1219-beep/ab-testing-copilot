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


def test_delta_method_equals_the_cluster_robust_sandwich():
    # For a row-level mean with rows nested in users, OLS on an arm indicator gives the
    # difference of ratios sum(x) / sum(d), and its cluster-robust (CR0) variance equals the
    # delta-method variance times (n - 1) / n per arm. With equal arms the factor is common.
    sm = pytest.importorskip("statsmodels.api")
    rng = np.random.default_rng(7)
    n = 300
    d = rng.integers(1, 12, size=2 * n)
    propensity = rng.beta(2, 8, size=2 * n)
    arm = np.repeat([0.0, 1.0], n)
    user = np.repeat(np.arange(2 * n), d)
    y = rng.binomial(1, np.clip(propensity[user] + 0.05 * arm[user], 0, 1)).astype(float)
    x = np.bincount(user, weights=y)
    ours = an.compare_ratios(x[:n], d[:n], x[n:], d[n:])
    fit = sm.OLS(y, sm.add_constant(arm[user])).fit(
        cov_type="cluster", cov_kwds={"groups": user, "use_correction": False})
    assert ours.absolute_effect == pytest.approx(fit.params[1], rel=1e-10)
    assert ours.std_error * math.sqrt((n - 1) / n) == pytest.approx(fit.bse[1], rel=1e-9)


def test_novelty_trend_matches_weighted_least_squares():
    sm = pytest.importorskip("statsmodels.api")
    from ab_testing_copilot.novelty import effect_trend

    rng = np.random.default_rng(8)
    x = np.arange(12.0)
    se = rng.uniform(0.005, 0.02, 12)
    y = 0.05 - 0.003 * x + rng.normal(0, 3 * se)  # scatter beyond the stated standard errors
    slope, slope_se, stat, dof, p, _ = effect_trend(x, y, se)
    fit = sm.WLS(y, sm.add_constant(x), weights=1 / se**2).fit()
    assert fit.scale > 1  # so the residual scale, not the floor of 1, is in use
    assert slope == pytest.approx(fit.params[1], rel=1e-10)
    assert slope_se == pytest.approx(fit.bse[1], rel=1e-10)
    assert (stat, dof) == (pytest.approx(fit.tvalues[1], rel=1e-10), int(fit.df_resid))
    assert p == pytest.approx(fit.pvalues[1], rel=1e-9)


def test_cochran_q_matches_statsmodels_meta_analysis():
    meta = pytest.importorskip("statsmodels.stats.meta_analysis")
    from ab_testing_copilot.heterogeneity import cochran_q

    rng = np.random.default_rng(9)
    effects, se = rng.normal(0.02, 0.015, 7), rng.uniform(0.004, 0.02, 7)
    q, dof, p, i2, pooled = cochran_q(effects, se)
    ref = meta.combine_effects(effects, se**2, method_re="dl")
    test = ref.test_homogeneity()
    assert (q, dof) == (pytest.approx(test.statistic, rel=1e-10), test.df)
    assert p == pytest.approx(test.pvalue, rel=1e-10)
    assert i2 == pytest.approx(max(0.0, ref.i2), rel=1e-10)
    assert pooled == pytest.approx(ref.mean_effect_fe, rel=1e-10)
