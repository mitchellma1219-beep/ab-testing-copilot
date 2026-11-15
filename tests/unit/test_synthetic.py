"""Synthetic data generators: ground truth, determinism and input validation."""

import numpy as np
import pandas as pd
import pytest

from ab_testing_copilot.experiment import ExperimentConfig, MetricSpec, analyze_experiment
from ab_testing_copilot.synthetic import (
    SCENARIOS,
    SEGMENT_SHARES,
    SEGMENTS,
    make_experiment,
    make_scenario,
    make_sessions,
)


def test_experiment_is_deterministic_and_matches_its_ground_truth():
    a, b = make_experiment(n=50_000, lift=0.02), make_experiment(n=50_000, lift=0.02)
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(make_experiment(n=50_000, lift=0.02, seed=8))
    assert list(a.columns) == ["user_id", "variant", "converted", "revenue", "pre_spend",
                               "page_load_ms", "exposure_date", "segment"]
    assert a["user_id"].is_unique and set(a["variant"]) == {"control", "treatment"}
    rates = a.groupby("variant")["converted"].mean()
    assert rates["control"] == pytest.approx(0.10, abs=0.006)
    assert rates["treatment"] - rates["control"] == pytest.approx(0.02, abs=0.008)
    assert a["exposure_date"].nunique() == 14 and a["exposure_date"].min() == "2026-01-05"
    shares = a["segment"].value_counts(normalize=True)
    assert [shares[s] for s in SEGMENTS] == pytest.approx(list(SEGMENT_SHARES), abs=0.01)
    assert np.corrcoef(a["revenue"], a["pre_spend"])[0, 1] > 0.8  # a usable CUPED covariate


def test_experiment_options_change_only_what_they_say():
    base = make_experiment(n=20_000)
    slow = make_experiment(n=20_000, load_ms_shift=60.0)
    assert slow["converted"].equals(base["converted"])
    gap = slow.groupby("variant")["page_load_ms"].mean().diff().iloc[-1]
    assert gap == pytest.approx(60.0, abs=6.0)
    paid = make_experiment(n=20_000, revenue_effect=3.0)
    assert paid.groupby("variant")["revenue"].mean().diff().iloc[-1] == pytest.approx(3.0, abs=0.6)
    lost = make_experiment(n=20_000, lift=0.0, srm_drop=0.15)
    assert len(lost) < len(base) and (lost["variant"] == "control").mean() < 0.48
    fading = make_experiment(n=60_000, lift=0.06, novelty_half_life=3.0)
    early = fading[fading["exposure_date"] <= "2026-01-07"].groupby("variant")["converted"].mean()
    late = fading[fading["exposure_date"] >= "2026-01-16"].groupby("variant")["converted"].mean()
    assert early.diff().iloc[-1] > 0.03 > 0.015 > late.diff().iloc[-1]
    mobile = make_experiment(n=60_000, lift=0.0, segment_lifts={"mobile": 0.03})
    by_segment = mobile.groupby(["segment", "variant"])["converted"].mean().unstack()
    lift = by_segment["treatment"] - by_segment["control"]
    assert lift["mobile"] > 0.015 and abs(lift["desktop"]) < 0.012


@pytest.mark.parametrize("kwargs", [
    {"n": 0}, {"days": 0}, {"treatment_share": 0.0}, {"treatment_share": 1.0},
    {"srm_drop": 1.0}, {"srm_drop": -0.1}, {"novelty_half_life": 0.0},
    {"segment_lifts": {"watch": 0.1}},
])
def test_experiment_rejects_bad_parameters(kwargs):
    with pytest.raises(ValueError):
        make_experiment(**kwargs)


def test_sessions_are_nested_in_users_with_a_known_ratio():
    s = make_sessions(n_users=20_000, ctr_lift=0.02, seed=3)
    assert list(s.columns) == ["user_id", "variant", "session_id", "impressions", "clicks"]
    assert s["session_id"].is_unique and s.groupby("user_id")["variant"].nunique().max() == 1
    assert s.groupby("user_id").size().mean() == pytest.approx(5.0, abs=0.1)
    totals = s.groupby("variant")[["clicks", "impressions"]].sum()
    ctr = totals["clicks"] / totals["impressions"]
    assert ctr["control"] == pytest.approx(0.10, abs=0.005)
    assert ctr["treatment"] - ctr["control"] == pytest.approx(0.02, abs=0.006)
    assert (s["clicks"] <= s["impressions"]).all()
    pd.testing.assert_frame_equal(s, make_sessions(n_users=20_000, ctr_lift=0.02, seed=3))
    for kwargs in ({"n_users": 1}, {"mean_sessions": 0.5}, {"base_ctr": 0.0},
                   {"base_ctr": 0.5, "ctr_lift": 0.6}):
        with pytest.raises(ValueError):
            make_sessions(**kwargs)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_builds_and_can_be_analysed(name):
    df = make_scenario(name)
    assert len(df) >= 18_000 and SCENARIOS[name].title and SCENARIOS[name].truth
    report = analyze_experiment(df, ExperimentConfig(
        primary=MetricSpec(column="converted", type="binary"), unit_col="user_id"))
    assert report.decision.value in {"Ship", "Do not ship", "Inconclusive"}
    with pytest.raises(ValueError, match="unknown scenario"):
        make_scenario("nope")


@pytest.mark.parametrize("seed", [7, 8, 9])
def test_the_sample_ratio_mismatch_scenario_describes_the_artefact_it_contains(seed):
    # Losing 15% of the non-converting control users lifts the control rate from 0.10 to
    # 0.10 / (0.10 + 0.90 * 0.85) = 0.1156, so a treatment that does nothing looks 1.56 points
    # worse. The scenario text must say "loss", and the engine must not turn it into a verdict.
    df = make_scenario("sample_ratio_mismatch", seed)
    rates = df.groupby("variant")["converted"].mean()
    assert rates["treatment"] - rates["control"] == pytest.approx(-0.0156, abs=0.015)
    assert rates["treatment"] < rates["control"]
    truth = SCENARIOS["sample_ratio_mismatch"].truth
    assert "apparent loss" in truth and "win" not in truth
    report = analyze_experiment(df, ExperimentConfig(
        primary=MetricSpec(column="converted", type="binary"), unit_col="user_id"))
    assert report.decision.value == "Inconclusive" and report.evidence_quality == "invalid"
