import numpy as np
import pytest
from scipy import stats

from ab_testing_copilot import analysis as an


def test_proportions_match_scipy_chi_square():
    e = an.compare_proportions(480, 5000, 560, 5000)
    chi2, p, _, _ = stats.chi2_contingency([[480, 4520], [560, 4440]], correction=False)
    assert e.statistic**2 == pytest.approx(chi2, rel=1e-10)
    assert e.p_value == pytest.approx(p, rel=1e-10)
    assert e.absolute_effect == pytest.approx(0.016)
    se = np.sqrt(0.096 * 0.904 / 5000 + 0.112 * 0.888 / 5000)
    assert e.ci_low == pytest.approx(0.016 - stats.norm.ppf(0.975) * se)
    assert e.relative_effect == pytest.approx(0.112 / 0.096 - 1)
    assert e.rel_ci_low < e.relative_effect < e.rel_ci_high


def test_welch_matches_scipy():
    rng = np.random.default_rng(0)
    c, t = rng.normal(10, 2, 300), rng.normal(10.5, 4, 500)
    e = an.compare_means(c, t)
    ref = stats.ttest_ind(t, c, equal_var=False)
    ci = ref.confidence_interval(0.95)
    assert e.statistic == pytest.approx(ref.statistic, rel=1e-10)
    assert e.p_value == pytest.approx(ref.pvalue, rel=1e-9)
    assert (e.ci_low, e.ci_high) == pytest.approx((ci.low, ci.high), rel=1e-9)


def test_relative_ci_undefined_for_nonpositive_control():
    e = an.compare_means([-1.0, -2.0, -3.0], [1.0, 2.0, 3.0])
    assert e.relative_effect is None and e.rel_ci_low is None


def test_relative_ci_delta_method_against_simulation():
    rng = np.random.default_rng(1)
    c, t = rng.normal(50, 10, (4000, 400)), rng.normal(55, 10, (4000, 400))
    ratios = t.mean(axis=1) / c.mean(axis=1) - 1
    e = an.compare_means(c[0], t[0])
    width = (e.rel_ci_high - e.rel_ci_low) / (2 * stats.norm.ppf(0.975))
    assert width == pytest.approx(ratios.std(), rel=0.1)


def test_bootstrap_agrees_with_welch_on_well_behaved_data():
    rng = np.random.default_rng(2)
    c, t = rng.normal(0, 1, 800), rng.normal(0.2, 1, 800)
    est, lo, hi = an.bootstrap_mean_diff(c, t, n_boot=4000, seed=3)
    e = an.compare_means(c, t)
    assert est == pytest.approx(e.absolute_effect)
    assert lo == pytest.approx(e.ci_low, abs=0.015) and hi == pytest.approx(e.ci_high, abs=0.015)
    assert an.bootstrap_mean_diff(c, t, n_boot=500, seed=3) == an.bootstrap_mean_diff(
        c, t, n_boot=500, seed=3)


def test_cuped_is_unbiased_and_reduces_variance():
    rng = np.random.default_rng(4)
    n, rho = 20000, 0.8
    xc, xt = rng.normal(size=n), rng.normal(size=n)
    yc = rho * xc + np.sqrt(1 - rho**2) * rng.normal(size=n)
    yt = rho * xt + np.sqrt(1 - rho**2) * rng.normal(size=n) + 0.3
    yc_a, yt_a, theta, red = an.cuped_adjust(yc, xc, yt, xt)
    assert theta == pytest.approx(rho, abs=0.02)
    assert red == pytest.approx(rho**2, abs=0.02)
    assert yt_a.mean() - yc_a.mean() == pytest.approx(0.3, abs=0.03)
    assert yc_a.var() < 0.45 * yc.var()


def test_cuped_constant_covariate_is_noop():
    y = np.arange(10.0)
    yc, _, theta, red = an.cuped_adjust(y, np.ones(10), y + 1, np.ones(10))
    assert theta == 0 and red == 0 and np.array_equal(yc, y)


def test_pvalue_adjustments_match_known_values():
    p = [0.01, 0.04, 0.03, 0.005]
    assert an.adjust_pvalues(p, "bonferroni") == pytest.approx([0.04, 0.16, 0.12, 0.02])
    assert an.adjust_pvalues(p, "holm") == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert an.adjust_pvalues(p, "benjamini-hochberg") == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert an.adjust_pvalues(p, "benjamini-hochberg") == pytest.approx(
        list(stats.false_discovery_control(p, method="bh")))
    assert an.adjust_pvalues([]) == []


@pytest.mark.parametrize("bad", [[1.2], [-0.1], [float("nan")]])
def test_pvalue_adjustment_rejects_invalid(bad):
    with pytest.raises(ValueError):
        an.adjust_pvalues(bad)
    with pytest.raises(ValueError):
        an.adjust_pvalues([0.1], "nope")  # type: ignore[arg-type]


@pytest.mark.parametrize("args", [(5, 0, 5, 10), (11, 10, 5, 10), (-1, 10, 5, 10), (1, 10, 5, 0)])
def test_proportions_reject_impossible_counts(args):
    with pytest.raises(ValueError):
        an.compare_proportions(*args)


def test_degenerate_proportions_do_not_crash():
    e = an.compare_proportions(0, 100, 0, 100)
    assert e.p_value == 1.0 and e.absolute_effect == 0 and len(e.warnings) == 2
    assert e.relative_effect is None


def test_means_reject_nan_inf_and_tiny_samples():
    with pytest.raises(ValueError, match="NaN"):
        an.compare_means([1.0, float("nan")], [1.0, 2.0])
    with pytest.raises(ValueError, match="NaN or infinite"):
        an.compare_means([1.0, float("inf")], [1.0, 2.0])
    with pytest.raises(ValueError, match="at least 2"):
        an.compare_means([1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        an.bootstrap_mean_diff([1.0, 2.0], [1.0, 2.0], n_boot=10)


def test_zero_variance_means():
    same = an.compare_means([1.0] * 5, [1.0] * 5)
    assert same.p_value == 1.0 and any("zero variance" in w for w in same.warnings)
    diff = an.compare_means([1.0] * 5, [2.0] * 5)
    assert diff.p_value == 0.0 and any("zero variance" in w for w in diff.warnings)
