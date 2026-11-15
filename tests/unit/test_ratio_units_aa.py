"""Ratio metric (delta method), unit-level aggregation and the A/A check."""

import numpy as np
import pandas as pd
import pytest

from ab_testing_copilot import analysis as an
from ab_testing_copilot.aa import aa_check, aa_diagnostic
from ab_testing_copilot.synthetic import make_experiment, make_sessions
from ab_testing_copilot.units import aggregate_to_units, parse_aggregations


def test_ratio_with_unit_denominators_is_the_difference_in_means():
    rng = np.random.default_rng(0)
    c, t = rng.normal(10, 2, 500), rng.normal(10.3, 4, 700)
    ratio = an.compare_ratios(c, np.ones(500), t, np.ones(700))
    mean = an.compare_means(c, t)
    assert ratio.absolute_effect == pytest.approx(mean.absolute_effect, rel=1e-12)
    assert ratio.std_error == pytest.approx(mean.std_error, rel=1e-12)
    assert ratio.statistic == pytest.approx(mean.statistic, rel=1e-12)
    assert ratio.p_value == pytest.approx(mean.p_value, abs=2e-3)  # normal vs t reference
    assert ratio.metric_type == "ratio" and "delta-method" in ratio.method


def test_ratio_variance_matches_the_linearised_form():
    # Var(R) = var((x - R d) / d_bar) / n: the delta method written as a variance of
    # linearised unit values. Computed here without the covariance formula used in the code.
    rng = np.random.default_rng(1)
    d_c, d_t = rng.integers(1, 30, 400).astype(float), rng.integers(1, 30, 350).astype(float)
    x_c, x_t = rng.binomial(d_c.astype(int), 0.2), rng.binomial(d_t.astype(int), 0.25)
    e = an.compare_ratios(x_c, d_c, x_t, d_t)
    r_c, r_t = x_c.sum() / d_c.sum(), x_t.sum() / d_t.sum()
    lin_c, lin_t = (x_c - r_c * d_c) / d_c.mean(), (x_t - r_t * d_t) / d_t.mean()
    se = np.sqrt(lin_c.var(ddof=1) / 400 + lin_t.var(ddof=1) / 350)
    assert (e.control_value, e.treatment_value) == pytest.approx((r_c, r_t))
    assert e.std_error == pytest.approx(se, rel=1e-10)
    assert e.ci_low == pytest.approx(r_t - r_c - 1.959963984540054 * se, rel=1e-9)
    assert e.relative_effect == pytest.approx(r_t / r_c - 1)
    assert e.rel_ci_low < e.relative_effect < e.rel_ci_high


def test_ratio_standard_error_matches_simulation():
    rng = np.random.default_rng(2)
    n, sims = 600, 3000
    d = 1 + rng.poisson(8, size=(sims, 2, n)).astype(float)
    p = rng.beta(2, 18, size=(sims, 2, n))
    x = rng.binomial(d.astype(int), p).astype(float)
    ratios = x.sum(axis=2) / d.sum(axis=2)
    empirical = (ratios[:, 1] - ratios[:, 0]).std(ddof=1)
    e = an.compare_ratios(x[0, 0], d[0, 0], x[0, 1], d[0, 1])
    assert e.std_error == pytest.approx(empirical, rel=0.08)


def test_ratio_edge_cases():
    same = an.compare_ratios([2.0, 4.0, 6.0], [1.0, 2.0, 3.0], [4.0, 2.0, 8.0], [2.0, 1.0, 4.0])
    assert same.p_value == 1.0 and same.absolute_effect == 0
    assert len(same.warnings) == 2  # zero variance and fewer than 30 units
    negative = an.compare_ratios([-1.0, -2.0, -1.5], [1.0, 1.0, 1.0], [1.0, 2.0, 1.5],
                                 [1.0, 1.0, 1.0])
    assert negative.relative_effect is None and negative.rel_ci_low is None


@pytest.mark.parametrize("args, match", [
    (([1.0, 2.0, 3.0], [1.0, 1.0], [1.0, 2.0], [1.0, 1.0]), "same length"),
    (([1.0, 2.0], [1.0, -1.0], [1.0, 2.0], [1.0, 1.0]), ">= 0"),
    (([1.0, 2.0], [0.0, 0.0], [1.0, 2.0], [1.0, 1.0]), "undefined"),
    (([1.0, float("nan")], [1.0, 1.0], [1.0, 2.0], [1.0, 1.0]), "NaN"),
    (([1.0], [1.0], [1.0, 2.0], [1.0, 1.0]), "at least 2"),
])
def test_ratio_rejects_bad_input(args, match):
    with pytest.raises(ValueError, match=match):
        an.compare_ratios(*args)
    with pytest.raises(ValueError):
        an.compare_ratios([1.0, 2.0], [1.0, 1.0], [1.0, 2.0], [1.0, 1.0], alpha=0)


def _rows():
    return pd.DataFrame({
        "user": ["a", "a", "a", "b", "b", "c"],
        "variant": ["control"] * 3 + ["treatment"] * 3,
        "clicks": [1.0, 0.0, 2.0, 1.0, np.nan, 4.0],
        "purchased": [0, 1, 0, 0, 0, 1],
        "country": ["US", "US", "US", "DE", "DE", "FR"],
        "day": ["2026-01-07", "2026-01-05", "2026-01-06", "2026-01-05", "2026-01-09",
                "2026-01-08"],
    })


def test_aggregate_to_units():
    out = aggregate_to_units(_rows(), "user", {
        "clicks": "sum", "purchased": "max", "country": "unique", "day": "min"})
    assert list(out.columns) == ["user", "variant", "n_rows", "clicks", "purchased", "country",
                                 "day"]
    assert out["user"].tolist() == ["a", "b", "c"] and out["n_rows"].tolist() == [3, 2, 1]
    assert out["clicks"].iloc[0] == 3.0 and out["clicks"].iloc[2] == 4.0
    assert np.isnan(out["clicks"].iloc[1])  # a missing row keeps the unit's total missing
    assert out["purchased"].tolist() == [1, 0, 1]
    assert out["country"].tolist() == ["US", "DE", "FR"]
    assert out["day"].tolist() == ["2026-01-05", "2026-01-05", "2026-01-08"]
    means = aggregate_to_units(_rows(), "user", {"purchased": "mean", "clicks": "first",
                                                 "day": "max"})
    assert means["purchased"].tolist() == pytest.approx([1 / 3, 0.0, 1.0])
    assert means["clicks"].tolist() == [1.0, 1.0, 4.0]
    assert means["day"].iloc[0] == "2026-01-07"


def test_aggregate_keeps_contaminated_units_visible():
    df = pd.concat([_rows(), pd.DataFrame({
        "user": ["a"], "variant": ["treatment"], "clicks": [9.0], "purchased": [1],
        "country": ["US"], "day": ["2026-01-09"]})], ignore_index=True)
    out = aggregate_to_units(df, "user", {"clicks": "sum"})
    assert out[out["user"] == "a"]["variant"].tolist() == ["control", "treatment"]


@pytest.mark.parametrize("mutate, metrics, match", [
    (lambda d: d, {}, "at least one column"),
    (lambda d: d, {"nope": "sum"}, "missing required column"),
    (lambda d: d, {"clicks": "median"}, "unknown aggregation"),
    (lambda d: d, {"country": "sum"}, "must be numeric"),
    (lambda d: d, {"user": "first"}, "must all be different"),
    (lambda d: d.assign(n_rows=1), {"n_rows": "sum"}, "reserved"),
    (lambda d: d.assign(user=[None, "a", "a", "b", "b", "c"]), {"clicks": "sum"}, "missing 'user'"),
    (lambda d: d.assign(variant=["control", None, "control"] + ["treatment"] * 3),
     {"clicks": "sum"}, "missing 'variant'"),
    (lambda d: d.assign(country=["US", "CA", "US", "DE", "DE", "FR"]), {"country": "unique"},
     "not constant within 1 unit"),
    (lambda d: d.iloc[0:0], {"clicks": "sum"}, "no rows"),
])
def test_aggregate_rejects_bad_input(mutate, metrics, match):
    with pytest.raises(ValueError, match=match):
        aggregate_to_units(mutate(_rows()), "user", metrics)


def test_parse_aggregations():
    assert parse_aggregations("clicks=sum, country=unique") == {
        "clicks": "sum", "country": "unique"}
    for bad in ("clicks", "clicks=median", "=sum", "clicks=sum,clicks=max", ""):
        with pytest.raises(ValueError):
            parse_aggregations(bad)


def test_aa_check_is_calibrated_on_independent_units():
    df = make_experiment(n=6000)
    binary = aa_check(df, "converted", "binary", n_relabels=1000, seed=3)
    assert binary.verdict == "calibrated" and binary.n_units == 6000
    assert abs(binary.false_positive_rate - 0.05) < 4 * binary.mc_standard_error
    assert binary.ci_low < binary.false_positive_rate < binary.ci_high
    assert sum(binary.p_value_histogram) == 1000 and len(binary.p_value_histogram) == 10
    continuous = aa_check(df, "revenue", "continuous", unit_col="user_id", n_relabels=1000,
                          treatment_share=0.3, seed=3)
    assert continuous.verdict == "calibrated" and continuous.treatment_share == 0.3
    assert aa_diagnostic(continuous).passed
    again = aa_check(df, "converted", "binary", n_relabels=1000, seed=3)
    assert again == binary  # deterministic for a given seed


def test_aa_check_exposes_the_wrong_unit_of_analysis():
    sessions = make_sessions(n_users=1500, seed=5)
    sessions["ctr"] = sessions["clicks"] / sessions["impressions"]
    # Users are randomised, but the test is run on session rows: far too many rejections.
    naive = aa_check(sessions, "ctr", "continuous", unit_col="user_id", n_relabels=500, seed=1)
    assert naive.verdict == "inflated" and naive.false_positive_rate > 0.15
    diag = aa_diagnostic(naive)
    assert diag.severity == "blocking" and not diag.passed and "unit of analysis" in diag.message
    # Re-labelling rows instead of users hides the problem: the check must use the real unit.
    per_row = aa_check(sessions, "ctr", "continuous", n_relabels=500, seed=1)
    assert per_row.verdict == "calibrated"
    # The delta method on user-level sums is calibrated on the same data.
    delta = aa_check(sessions, "clicks", "ratio", denominator="impressions", unit_col="user_id",
                     n_relabels=500, seed=1)
    assert delta.verdict == "calibrated" and delta.n_units == 1500
    assert delta.n_rows == len(sessions)


def test_aa_check_reports_a_conservative_test():
    rng = np.random.default_rng(0)
    values = rng.normal(10, 1, 400)
    values[0] = 1e9  # one extreme unit dominates whichever arm it lands in
    res = aa_check(pd.DataFrame({"y": values}), "y", "continuous", n_relabels=400)
    assert res.verdict == "conservative" and res.false_positive_rate < 0.01
    diag = aa_diagnostic(res)
    assert diag.passed and diag.severity == "info" and "less often" in diag.message


def test_aa_check_ignores_rows_with_missing_values():
    df = make_experiment(n=3000)
    df["revenue"] = df["revenue"].where(df.index % 10 != 0)
    res = aa_check(df, "revenue", "continuous", n_relabels=200)
    assert res.n_rows == 2700 and res.n_units == 2700


@pytest.mark.parametrize("kwargs, match", [
    ({"n_relabels": 50}, "n_relabels"), ({"n_relabels": 50_000}, "n_relabels"),
    ({"alpha": 0.0}, "alpha"), ({"treatment_share": 1.0}, "treatment_share"),
    ({"metric": "nope"}, "missing required column"),
    ({"metric": "variant"}, "must be numeric"),
    ({"metric": "revenue", "metric_type": "binary"}, "other than 0/1"),
    ({"metric_type": "ratio"}, "needs a denominator"),
    ({"denominator": "revenue"}, "only meaningful for a ratio"),
    ({"unit_col": "missing_unit"}, "missing required column"),
    ({"treatment_share": 0.0005}, "at least 4 units per arm"),
])
def test_aa_check_rejects_bad_input(kwargs, match):
    args = {"metric": "converted", "metric_type": "binary", "n_relabels": 200, **kwargs}
    with pytest.raises(ValueError, match=match):
        aa_check(make_experiment(n=2000), **args)


def test_aa_check_rejects_unusable_values():
    df = make_experiment(n=500)
    with pytest.raises(ValueError, match="infinite"):
        aa_check(df.assign(revenue=np.where(df.index == 3, np.inf, df["revenue"])), "revenue",
                 "continuous", n_relabels=200)
    with pytest.raises(ValueError, match="at least 4 units"):
        aa_check(df.head(5), "revenue", "continuous", n_relabels=200)
    ratio = df.assign(den=0.0)
    with pytest.raises(ValueError, match="undefined"):
        aa_check(ratio, "revenue", "ratio", denominator="den", n_relabels=200)
    with pytest.raises(ValueError, match=">= 0"):
        aa_check(df.assign(den=-1.0), "revenue", "ratio", denominator="den", n_relabels=200)
