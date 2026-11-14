"""Sequential designs, novelty, segments, A/A and ratio metrics through the full pipeline."""

import json

import pytest

from ab_testing_copilot.cli import main
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
    novelty_analysis,
    segment_analysis,
)
from ab_testing_copilot.models import Decision
from ab_testing_copilot.report import render_markdown
from ab_testing_copilot.sequential import SequentialDesign, sequential_boundaries
from ab_testing_copilot.synthetic import make_experiment, make_scenario, make_sessions
from ab_testing_copilot.units import aggregate_to_units

BIN = MetricSpec(column="converted", type="binary")
LOAD = GuardrailSpec(column="page_load_ms", type="continuous", higher_is_better=False)


def _diag(report, name):
    return next(d for d in report.diagnostics if d.name == name)


def _design(look, looks=4, method="obrien-fleming", planned_n=8000):
    return SequentialDesign(method=method, planned_looks=looks, current_look=look,
                            planned_sample_size=planned_n)


def test_boundary_holds_back_a_result_that_a_fixed_test_would_ship():
    df = make_experiment(n=8000, lift=0.03)
    half = df.iloc[:4000]
    fixed = analyze_experiment(half, ExperimentConfig(primary=BIN))
    assert fixed.decision is Decision.SHIP and 1.96 < fixed.primary.statistic < 2.9631
    interim = analyze_experiment(half, ExperimentConfig(primary=BIN, sequential=_design(2)))
    assert interim.decision is Decision.INCONCLUSIVE
    assert interim.sequential.critical_value == pytest.approx(2.9631, abs=5e-5)
    assert interim.effective_alpha == pytest.approx(interim.sequential.nominal_alpha)
    assert interim.primary.ci_low < 0 < interim.primary.ci_high
    assert any("Continue to the next planned look" in r for r in interim.reasons)
    assert not any("underpowered" in r for r in interim.reasons)
    assert _diag(interim, "sequential_design").passed
    assert not any(d.name == "peeking" for d in interim.diagnostics)
    assert any("no futility" in a for a in interim.assumptions)
    md = render_markdown(interim)
    assert "## Sequential design" in md and "| 2 (this look) |" in md

    later = analyze_experiment(df.iloc[:6000], ExperimentConfig(primary=BIN,
                                                                sequential=_design(3)))
    assert later.decision is Decision.SHIP and later.primary.statistic > 2.3590
    assert any("was crossed at look 3 of 4" in r for r in later.reasons)
    assert any("overstate the effect" in r for r in later.reasons)


def test_final_look_uses_the_last_boundary_and_the_ordinary_wording():
    df = make_experiment(n=8000, lift=0.0, seed=3)
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, absolute_mde=0.03,
                                                sequential=_design(4)))
    final = sequential_boundaries(4, 0.05, "obrien-fleming").critical_values[-1]
    assert r.sequential.is_final and r.sequential.critical_value == pytest.approx(final)
    assert r.decision is Decision.INCONCLUSIVE and r.evidence_quality == "strong"
    assert any("ruled out" in x for x in r.reasons)
    assert not any("Continue" in x for x in r.reasons)
    assert "(final analysis)" in _diag(r, "sequential_design").message


def test_guardrails_share_the_sequential_critical_value():
    df = make_experiment(n=8000, lift=0.03).iloc[:4000]
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, guardrails=[LOAD],
                                                sequential=_design(2, method="pocock")))
    assert r.guardrails[0].estimate.alpha == pytest.approx(r.sequential.nominal_alpha)
    assert r.effective_alpha == pytest.approx(r.sequential.nominal_alpha)


def test_unplanned_looks_keep_bonferroni_and_tighten_the_guardrail_pass():
    cfg = ExperimentConfig(primary=BIN, guardrails=[LOAD], n_looks=5)
    r = analyze_experiment(make_experiment(n=8000, lift=0.03, seed=1), cfg)
    assert r.effective_alpha == pytest.approx(0.01) and not _diag(r, "peeking").passed
    assert r.sequential is None
    g = r.guardrails[0]
    assert g.estimate.alpha == 0.05  # the reported interval and the harm flag stay unadjusted
    assert g.status == "pass" and "at the 99.0% level" in g.message
    assert any("Bonferroni level" in a for a in r.assumptions)
    # In this draw page load is slower in treatment by chance (p < 0.05 but not < 0.01): the
    # regression is still flagged at the unadjusted level, as before.
    flagged = analyze_experiment(make_experiment(n=8000, lift=0.03, seed=3), cfg)
    assert flagged.guardrails[0].status == "fail" and flagged.decision is Decision.DO_NOT_SHIP
    assert 0.01 < flagged.guardrails[0].estimate.p_value < 0.05


def test_final_look_short_of_the_planned_sample_weakens_the_evidence():
    df = make_experiment(n=6500, lift=0.06)
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, sequential=_design(4)))
    warning = _diag(r, "sequential_sample")
    assert warning.severity == "warning" and not warning.passed and "81.2%" in warning.message
    assert r.evidence_quality == "weak" and r.sequential.observed_fraction == 0.8125


def test_novelty_decay_is_a_warning_that_leaves_the_decision_alone():
    df = make_scenario("novelty_decay")
    cfg = ExperimentConfig(primary=BIN, unit_col="user_id")
    plain = analyze_experiment(df, cfg)
    dated = analyze_experiment(df, cfg.model_copy(update={"date_col": "exposure_date"}))
    assert plain.decision is Decision.SHIP and plain.evidence_quality == "strong"
    assert dated.decision is plain.decision and dated.primary == plain.primary
    assert dated.evidence_quality == "weak"
    d = _diag(dated, "novelty_effect")
    assert d.severity == "warning" and not d.passed and "warning, not proof" in d.message
    nov = dated.novelty
    assert nov.decay_detected and len(nov.periods) == 14 and nov.slope < 0
    assert nov.periods[0].label == "2026-01-05" and nov.early_effect > nov.late_effect
    assert any("Possible novelty effect" in r for r in dated.reasons)
    assert "## Effect over time (novelty check)" in render_markdown(dated)
    assert novelty_analysis(df, cfg.model_copy(update={"date_col": "exposure_date"})) == nov
    with pytest.raises(ValueError):
        novelty_analysis(df, cfg)


def test_stable_effect_has_no_novelty_warning_and_weekly_bins_need_more_weeks():
    df = make_scenario("clean_win")
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, date_col="exposure_date"))
    assert _diag(r, "novelty_effect").passed and r.evidence_quality == "strong"
    weekly = analyze_experiment(df, ExperimentConfig(primary=BIN, date_col="exposure_date",
                                                     date_bin_days=7))
    d = _diag(weekly, "novelty_effect")
    assert not d.assessed and d.passed and "only 2 usable period(s)" in d.message
    assert weekly.novelty.assessed is False and weekly.evidence_quality == "strong"


def test_segments_are_exploratory_and_never_change_the_decision():
    df = make_scenario("segment_heterogeneity")
    cfg = ExperimentConfig(primary=BIN, guardrails=[LOAD], unit_col="user_id")
    plain = analyze_experiment(df, cfg)
    cut = analyze_experiment(df, cfg.model_copy(update={"segment_col": "segment"}))
    assert (cut.decision, cut.evidence_quality, cut.reasons, cut.primary, cut.guardrails) == (
        plain.decision, plain.evidence_quality, plain.reasons, plain.primary, plain.guardrails)
    assert [d for d in cut.diagnostics if d.name != "segments_exploratory"] == plain.diagnostics
    seg = cut.segments
    assert seg.exploratory is True and seg.heterogeneity_detected and seg.q_p_value < 0.001
    by_name = {s.segment: s for s in seg.segments}
    assert set(by_name) == {"desktop", "mobile", "tablet"}
    assert by_name["mobile"].significant_after_correction
    assert not by_name["desktop"].significant_after_correction
    assert by_name["mobile"].simultaneous_ci_low <= 0.03 <= by_name["mobile"].simultaneous_ci_high
    d = _diag(cut, "segments_exploratory")
    assert d.passed and d.severity == "info"
    md = render_markdown(cut)
    assert "## Segments (exploratory)" in md and "hypothesis-generating only" in md
    assert segment_analysis(df, cfg.model_copy(update={"segment_col": "segment"})) == seg
    with pytest.raises(ValueError):
        segment_analysis(df, cfg)


def test_opposite_segment_effects_do_not_rescue_or_sink_the_decision():
    df = make_experiment(n=40000, lift=0.0, segment_lifts={"mobile": 0.05, "desktop": -0.04})
    plain = analyze_experiment(df, ExperimentConfig(primary=BIN))
    cut = analyze_experiment(df, ExperimentConfig(primary=BIN, segment_col="segment",
                                                  segment_correction="bonferroni"))
    assert plain.decision is Decision.INCONCLUSIVE and cut.decision is Decision.INCONCLUSIVE
    assert cut.evidence_quality == plain.evidence_quality == "strong"
    signs = {s.segment: s.estimate.absolute_effect > 0 for s in cut.segments.segments
             if s.significant_after_correction}
    assert signs == {"desktop": False, "mobile": True}
    assert cut.segments.correction == "bonferroni"


def test_aa_check_in_the_pipeline():
    df = make_experiment(n=6000)
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, unit_col="user_id",
                                                aa_relabels=300, seed=5))
    assert r.aa_check.verdict == "calibrated" and r.aa_check.n_relabels == 300
    assert r.aa_check.seed == 5 and _diag(r, "aa_check").passed
    plain = analyze_experiment(df, ExperimentConfig(primary=BIN, unit_col="user_id"))
    assert (r.decision, r.evidence_quality, r.primary) == (
        plain.decision, plain.evidence_quality, plain.primary)  # a calibrated check adds nothing
    same = analyze_experiment(df, ExperimentConfig(primary=BIN, unit_col="user_id",
                                                   aa_relabels=300, seed=5))
    assert same.aa_check == r.aa_check


def test_ratio_metric_on_aggregated_sessions_recovers_the_truth():
    sessions = make_sessions(n_users=6000, ctr_lift=0.02, seed=4)
    users = aggregate_to_units(sessions, "user_id", {"clicks": "sum", "impressions": "sum"})
    assert len(users) == 6000 and users["n_rows"].sum() == len(sessions)
    ctr = MetricSpec(column="clicks", type="ratio", denominator="impressions")
    r = analyze_experiment(users, ExperimentConfig(
        primary=ctr, unit_col="user_id", absolute_mde=0.02,
        guardrails=[GuardrailSpec(column="impressions", type="ratio", denominator="n_rows")]))
    assert r.decision is Decision.SHIP and r.primary.metric == "clicks/impressions"
    assert r.primary.ci_low <= 0.02 <= r.primary.ci_high and r.primary.metric_type == "ratio"
    assert r.primary.control_value == pytest.approx(0.10, abs=0.01)
    assert r.guardrails[0].estimate.metric == "impressions/n_rows"
    assert any(d.name == "outliers_control" for d in r.diagnostics)
    with_cov = analyze_experiment(users.assign(pre=1.0), ExperimentConfig(
        primary=ctr, covariate_col="pre"))
    assert not _diag(with_cov, "cuped").assessed and with_cov.primary == r.primary


def test_cli_sequential_novelty_segments_and_aa(tmp_path, capsys):
    path = tmp_path / "exp.csv"
    make_experiment(n=8000, lift=0.03).iloc[:4000].to_csv(path, index=False)
    base = ["analyze", str(path), "--metric", "converted", "--metric-type", "binary",
            "--unit-col", "user_id"]
    assert main([*base, "--sequential", "obrien-fleming", "--planned-looks", "4", "--look", "2",
                 "--planned-n", "8000", "--date-col", "exposure_date", "--segment-col",
                 "segment", "--aa-relabels", "200", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "Inconclusive"
    assert payload["sequential"]["current_look"] == 2
    assert payload["sequential"]["critical_value"] == pytest.approx(2.9631, abs=5e-5)
    assert payload["novelty"]["assessed"] and payload["segments"]["exploratory"] is True
    assert payload["aa_check"]["verdict"] == "calibrated"

    assert main([*base, "--info-fractions", "0.3,0.6,1", "--sequential", "pocock",
                 "--planned-looks", "3", "--look", "1"]) == 0
    assert "Pocock-type" in capsys.readouterr().out
    for bad in (["--look", "2"], ["--sequential", "pocock", "--look", "2"],
                ["--sequential", "pocock", "--planned-looks", "2", "--look", "3"],
                ["--sequential", "pocock", "--planned-looks", "2", "--look", "1", "--looks", "3"],
                ["--planned-n", "8000"], ["--aa-relabels", "5"], ["--date-bin-days", "0"]):
        assert main([*base, *bad]) == 1
        assert "error:" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main([*base, "--info-fractions", "a,b"])


def test_cli_ratio_metric_with_aggregation(tmp_path, capsys):
    path = tmp_path / "sessions.csv"
    make_sessions(n_users=3000, ctr_lift=0.03, seed=2).to_csv(path, index=False)
    args = ["analyze", str(path), "--metric", "clicks", "--metric-type", "ratio",
            "--denominator", "impressions", "--unit-col", "user_id", "--format", "json"]
    assert main(args) == 0  # session rows as they are: refused as the wrong unit of analysis
    raw = json.loads(capsys.readouterr().out)
    assert raw["evidence_quality"] == "invalid" and raw["decision"] == "Inconclusive"
    assert main([*args, "--aggregate", "clicks=sum,impressions=sum",
                 "--guardrail", "impressions/n_rows:ratio:higher:0.05"]) == 0
    agg = json.loads(capsys.readouterr().out)
    assert agg["decision"] == "Ship" and agg["primary"]["metric"] == "clicks/impressions"
    assert agg["primary"]["n_control"] + agg["primary"]["n_treatment"] == 3000
    assert agg["guardrails"][0]["estimate"]["metric"] == "impressions/n_rows"
    for bad in ([*args, "--aggregate", "clicks=sum"],  # impressions not carried over
                [*args, "--guardrail", "impressions/n_rows:ratio"],  # n_rows needs --aggregate
                ["analyze", str(path), "--metric", "clicks", "--metric-type", "ratio"],
                ["analyze", str(path), "--metric", "clicks", "--metric-type", "continuous",
                 "--aggregate", "clicks=sum"],  # --aggregate needs --unit-col
                [*args, "--aggregate", "clicks=median"]):
        assert main(bad) == 1
        assert "error:" in capsys.readouterr().err
    with pytest.raises(SystemExit):  # a ratio guardrail must name its denominator
        main([*args, "--guardrail", "impressions:ratio"])


def test_cli_sequential_and_aa_commands(tmp_path, capsys):
    assert main(["sequential", "--method", "obrien-fleming", "--looks", "5"]) == 0
    out = capsys.readouterr().out
    assert "| 2 | 0.400 | 3.3570 |" in out and "1.0247 x the fixed-horizon size" in out
    assert main(["sequential", "--method", "pocock", "--info-fractions", "0.001,0.5,1",
                 "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["critical_values"][-1] > 2 and payload["inflation_factor"] > 1
    assert main(["sequential", "--method", "obrien-fleming", "--info-fractions", "0.001,0.5,1",
                 "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["critical_values"][0] is None  # strict JSON
    assert main(["sequential", "--method", "pocock"]) == 1
    assert main(["sequential", "--method", "pocock", "--looks", "3", "--info-fractions",
                 "0.5,1"]) == 1
    assert main(["sequential", "--method", "pocock", "--looks", "500"]) == 1
    capsys.readouterr()

    assert main(["design", "--baseline", "0.1", "--mde", "0.02", "--sequential", "pocock",
                 "--looks", "5", "--daily-units", "1000"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["n_control"] == 3841 and d["sequential"]["n_control_max"] > 4400
    assert d["duration_days"] == 10 and len(d["sequential"]["critical_values"]) == 5
    assert not any("single look" in a for a in d["assumptions"])
    assert main(["design", "--baseline", "0.1", "--mde", "0.02", "--looks", "5"]) == 1
    assert main(["design", "--baseline", "0.1", "--mde", "0.02", "--sequential", "pocock"]) == 1
    capsys.readouterr()

    path = tmp_path / "sessions.csv"
    sessions = make_sessions(n_users=1500, seed=5)
    sessions.assign(ctr=sessions["clicks"] / sessions["impressions"]).to_csv(path, index=False)
    assert main(["aa", str(path), "--metric", "ctr", "--metric-type", "continuous",
                 "--unit-col", "user_id", "--relabels", "300"]) == 4
    assert json.loads(capsys.readouterr().out)["verdict"] == "inflated"
    assert main(["aa", str(path), "--metric", "clicks", "--metric-type", "ratio",
                 "--denominator", "impressions", "--unit-col", "user_id", "--relabels",
                 "300"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "calibrated"
    assert main(["aa", str(path), "--metric", "ctr", "--metric-type", "continuous",
                 "--relabels", "3"]) == 1
    assert "error:" in capsys.readouterr().err
