"""Branches that only unusual input reaches: each must fail loudly or degrade explicitly."""

import json
import runpy
import sys

import numpy as np
import pandas as pd
import pytest

from ab_testing_copilot import analysis as an
from ab_testing_copilot import design, experiment
from ab_testing_copilot import diagnostics as dg
from ab_testing_copilot import sequential as sq
from ab_testing_copilot.cli import main
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
)
from ab_testing_copilot.models import Decision
from ab_testing_copilot.plan import PlanRequest
from ab_testing_copilot.sequential import SequentialDesign
from ab_testing_copilot.synthetic import make_experiment

BIN = MetricSpec(column="converted", type="binary")


def _diag(report, name):
    return next(d for d in report.diagnostics if d.name == name)


def _panel(days, per_day):
    """``per_day`` rows on each of ``days`` days, arms alternating, one row per unit."""
    n = days * per_day
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "variant": np.where(np.arange(n) % 2 == 0, "control", "treatment"),
        "day": np.repeat(np.arange(days), per_day),
        "converted": (rng.random(n) < 0.3).astype(int),
        "clicks": rng.poisson(3, n).astype(float),
        "views": rng.integers(1, 9, n).astype(float),
        "segment": np.where(np.repeat(np.arange(days), per_day) % 2 == 0, "even", "odd"),
    })


def test_cuped_with_an_unrelated_covariate_reports_the_raw_estimate():
    df = make_experiment(n=4000)
    df["noise"] = np.random.default_rng(1).normal(size=len(df))
    r = analyze_experiment(df, ExperimentConfig(
        primary=MetricSpec(column="revenue", type="continuous"), covariate_col="noise"))
    cuped = _diag(r, "cuped")
    assert cuped.passed and "negligible" in cuped.message and "CUPED" not in r.primary.method
    assert _diag(r, "covariate_balance").passed


def test_more_periods_than_the_limit_are_not_assessed():
    r = analyze_experiment(_panel(401, 120), ExperimentConfig(primary=BIN, date_col="day"))
    d = _diag(r, "novelty_effect")
    assert not d.assessed and "401 periods exceed the limit of 400" in d.message
    weekly = analyze_experiment(_panel(401, 120), ExperimentConfig(
        primary=BIN, date_col="day", date_bin_days=7))
    assert weekly.novelty.assessed and len(weekly.novelty.periods) == 58


def test_periods_that_cannot_be_estimated_are_left_out_and_counted():
    df = _panel(10, 200)
    df.loc[df["day"] == 3, "converted"] = 0  # no variation at all on day 3
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, date_col="day"))
    assert r.novelty.assessed and len(r.novelty.periods) == 9
    assert r.novelty.excluded_periods == 1 and 3 not in {p.index for p in r.novelty.periods}
    ratio = MetricSpec(column="clicks", type="ratio", denominator="views")
    broken = _panel(10, 200)
    broken.loc[(broken["day"] == 5) & (broken["variant"] == "control"), "views"] = 0.0
    r = analyze_experiment(broken, ExperimentConfig(primary=ratio, date_col="day"))
    assert len(r.novelty.periods) == 9 and r.novelty.excluded_periods == 1
    assert "1 period(s) were left out" in r.novelty.message


def test_a_segment_that_cannot_be_estimated_is_skipped_with_its_reason():
    ratio = MetricSpec(column="clicks", type="ratio", denominator="views")
    df = _panel(10, 200)
    df.loc[(df["segment"] == "odd") & (df["variant"] == "treatment"), "views"] = 0.0
    r = analyze_experiment(df, ExperimentConfig(primary=ratio, segment_col="segment"))
    assert [s.segment for s in r.segments.segments] == ["even"]
    assert r.segments.skipped[0].segment == "odd"
    assert "undefined" in r.segments.skipped[0].reason
    assert r.segments.q_statistic is None  # one usable segment: no heterogeneity test


def test_dates_that_pandas_cannot_parse_at_all_are_treated_as_missing(monkeypatch):
    def boom(*_args, **_kwargs):
        raise TypeError("not date-like")

    monkeypatch.setattr(experiment.pd, "to_datetime", boom)
    idx, names = experiment.period_index(pd.Series(["2026-01-05", "2026-01-06"]))
    assert idx.isna().all() and names == {}


def test_interim_win_with_an_unresolved_guardrail_says_continue():
    df = make_experiment(n=4000, lift=0.12)
    r = analyze_experiment(df, ExperimentConfig(
        primary=BIN,
        guardrails=[GuardrailSpec(column="revenue", type="continuous", margin=0.0001)],
        sequential=SequentialDesign(method="obrien-fleming", planned_looks=4, current_look=2)))
    assert abs(r.primary.statistic) > r.sequential.critical_value
    assert r.guardrails[0].status == "uncertain" and r.decision is Decision.INCONCLUSIVE
    assert r.reasons[-1] == "Continue to the next planned look to resolve the guardrails."


def test_a_last_fraction_within_rounding_of_one_is_accepted():
    b = sq.sequential_boundaries(alpha=0.05, method="pocock",
                                 information_fractions=[0.5, 1.0 - 1e-12])
    assert b.information_fractions == [0.5, 1.0] and b.cumulative_alpha[-1] == 0.05


def test_effect_chart_skips_metrics_whose_relative_interval_is_not_finite():
    charts = pytest.importorskip("ab_testing_copilot.charts")
    r = analyze_experiment(make_experiment(n=2000), ExperimentConfig(primary=BIN))
    odd = r.model_copy(update={"primary": r.primary.model_copy(
        update={"rel_ci_high": float("inf")})})
    assert not charts.effects_figure(odd).data


@pytest.mark.parametrize("override, match", [
    ({"baseline": float("nan")}, "baseline must be finite"),
    ({"baseline": float("inf")}, "baseline must be finite"),
    ({"metric_type": "continuous", "std_dev": 0.0}, "std_dev must be > 0"),
    ({"metric_type": "continuous"}, "needs its standard deviation"),
    ({"guardrails": []}, "state why none applies"),
    ({"guardrails": [], "no_guardrails_reason": "   "}, "state why none applies"),
    ({"looks": 3}, "needs a sequential method"),
])
def test_plan_request_validates_directly(override, match):
    base = dict(
        hypothesis="h", metric="converted", metric_type="binary", higher_is_better=True,
        baseline=0.1, mde=0.02, mde_is_relative=False, alpha=0.05, power=0.8,
        treatment_share=0.5, unit="user_id", daily_units=1000, traffic_share=1.0,
        guardrails=[{"name": "g", "type": "binary", "higher_is_better": True, "margin": 0.1}],
        looks=1)
    with pytest.raises(ValueError, match=match):
        PlanRequest(**{**base, **override})


def test_cli_edges(capsys, monkeypatch):
    with pytest.raises(SystemExit):
        main(["analyze", "x.csv", "--metric", "m", "--metric-type", "binary", "--guardrail",
              "g:binary:sideways"])
    capsys.readouterr()
    assert main(["simulate", "--n-sims", "200", "--format", "json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 24
    monkeypatch.setattr(sys, "argv", ["abcopilot", "srm", "5000", "5400"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("ab_testing_copilot", run_name="__main__")
    assert exit_info.value.code == 2 and "Sample ratio mismatch" in capsys.readouterr().out


@pytest.mark.parametrize("call", [
    lambda: design.power_for_proportions(0.1, 0.02, 0, 10),
    lambda: design.power_for_proportions(0.99, 0.02, 10, 10),
    lambda: design.power_for_means(1.0, 0.1, 10, 0),
    lambda: design.power_for_means(0.0, 0.1, 10, 10),
    lambda: design.duration_days(0, 10),
    lambda: dg.missing_data_check(0, 0, 0, 10),
    lambda: an.compare_proportions(1, 10, 2, 10, alpha=1.0),
    lambda: an.compare_means([1.0, 2.0], [1.0, 3.0], alpha=0.0),
    lambda: an.cuped_adjust([1.0, 2.0], [1.0, 2.0, 3.0], [1.0, 2.0], [1.0, 2.0]),
])
def test_remaining_input_validation(call):
    with pytest.raises(ValueError):
        call()
