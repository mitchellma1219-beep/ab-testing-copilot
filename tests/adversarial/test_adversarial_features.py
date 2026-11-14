"""Misuse and hostile input for the sequential, novelty, segment, A/A and ratio features.

Every case must fail loudly, be flagged, or be reported as "not assessed". None may mislead.
"""

import json
import re

import numpy as np
import pandas as pd
import pytest

from ab_testing_copilot import sequential as sq
from ab_testing_copilot.cli import main
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
    period_index,
)
from ab_testing_copilot.models import Decision
from ab_testing_copilot.report import render_markdown
from ab_testing_copilot.sequential import SequentialDesign
from ab_testing_copilot.synthetic import make_experiment, make_scenario, make_sessions
from ab_testing_copilot.units import aggregate_to_units

BIN = MetricSpec(column="converted", type="binary")
CTR = MetricSpec(column="clicks", type="ratio", denominator="impressions")


def _diag(report, name):
    return next(d for d in report.diagnostics if d.name == name)


def _obf(look, looks=4, **kwargs):
    return SequentialDesign(method="obrien-fleming", planned_looks=looks, current_look=look,
                            **kwargs)


# --- wrong unit of analysis -------------------------------------------------------------

def test_session_rows_are_refused_and_every_dependent_check_says_so():
    sessions = make_sessions(n_users=2000, ctr_lift=0.03, seed=3)
    sessions["day"] = np.arange(len(sessions)) % 14
    r = analyze_experiment(sessions, ExperimentConfig(
        primary=CTR, unit_col="user_id", date_col="day", aa_relabels=200))
    assert r.decision is Decision.INCONCLUSIVE and r.evidence_quality == "invalid"
    assert not _diag(r, "unit_of_analysis").passed
    novelty = _diag(r, "novelty_effect")
    assert not novelty.assessed and "not one per randomised unit" in novelty.message
    # the ratio estimate itself is on user sums only after aggregation; here rows were used
    assert r.primary.n_control + r.primary.n_treatment == len(sessions)


def test_row_level_test_on_clustered_rows_is_exposed_by_the_aa_check():
    sessions = make_sessions(n_users=1500, seed=6)
    sessions["ctr"] = sessions["clicks"] / sessions["impressions"]
    r = analyze_experiment(sessions, ExperimentConfig(
        primary=MetricSpec(column="ctr", type="continuous"), unit_col="user_id",
        aa_relabels=300))
    aa = _diag(r, "aa_check")
    assert aa.severity == "blocking" and not aa.passed
    assert r.aa_check.verdict == "inflated" and r.aa_check.false_positive_rate > 0.15
    assert r.evidence_quality == "invalid" and any("A/A check" in x for x in r.reasons)


def test_without_a_unit_column_the_naive_analysis_would_look_like_a_win():
    # Documented limitation: the tool cannot detect clustering if it is not told the unit.
    # With the unit declared, the same data are refused.
    hit = None
    for seed in range(40):
        sessions = make_sessions(n_users=300, mean_sessions=20, ctr_lift=0.0, seed=seed)
        sessions["ctr"] = sessions["clicks"] / sessions["impressions"]
        naive = analyze_experiment(sessions, ExperimentConfig(
            primary=MetricSpec(column="ctr", type="continuous")))
        if naive.decision is not Decision.INCONCLUSIVE:
            hit = sessions
            break
    assert hit is not None, "no false positive among 40 null datasets: clustering has no bite"
    told = analyze_experiment(hit, ExperimentConfig(
        primary=MetricSpec(column="ctr", type="continuous"), unit_col="user_id"))
    assert told.decision is Decision.INCONCLUSIVE and told.evidence_quality == "invalid"
    users = aggregate_to_units(hit, "user_id", {"clicks": "sum", "impressions": "sum"})
    proper = analyze_experiment(users, ExperimentConfig(primary=CTR, unit_col="user_id"))
    assert proper.decision is Decision.INCONCLUSIVE and proper.evidence_quality != "invalid"


# --- contaminated samples ---------------------------------------------------------------

def test_contamination_survives_aggregation_and_blocks_everything():
    sessions = make_sessions(n_users=1500, ctr_lift=0.05, seed=2)
    leak = sessions[sessions["variant"] == "control"].head(300).assign(variant="treatment")
    users = aggregate_to_units(pd.concat([sessions, leak]), "user_id",
                               {"clicks": "sum", "impressions": "sum"})
    assert users["user_id"].duplicated().any()
    r = analyze_experiment(users, ExperimentConfig(
        primary=CTR, unit_col="user_id", sequential=_obf(4)))
    assert r.evidence_quality == "invalid" and not _diag(r, "contamination").passed
    assert r.decision is Decision.INCONCLUSIVE


def test_a_boundary_crossing_does_not_override_a_sample_ratio_mismatch():
    df = make_scenario("sample_ratio_mismatch")
    naive = analyze_experiment(df, ExperimentConfig(primary=BIN, sequential=_obf(4)))
    assert abs(naive.primary.statistic) > naive.sequential.critical_value  # "crossed"
    assert naive.decision is Decision.INCONCLUSIVE and naive.evidence_quality == "invalid"
    cut = analyze_experiment(df, ExperimentConfig(primary=BIN, segment_col="segment",
                                                  date_col="exposure_date"))
    assert cut.decision is Decision.INCONCLUSIVE and cut.evidence_quality == "invalid"


# --- misuse of sequential boundaries ----------------------------------------------------

def test_a_plan_cannot_be_combined_with_unplanned_looks():
    with pytest.raises(ValueError, match="not both"):
        ExperimentConfig(primary=BIN, n_looks=3, sequential=_obf(2))


def test_a_look_outside_the_plan_has_no_boundary():
    with pytest.raises(ValueError, match="exceeds planned_looks"):
        _obf(5, looks=4)


def test_claiming_the_final_look_with_a_fraction_of_the_sample_is_refused():
    # The last boundary (2.01) is far easier to cross than the second (2.96). Declaring
    # "look 4 of 4" on data that only fill look 2 must not be accepted.
    df = make_experiment(n=8000, lift=0.03).iloc[:4000]
    honest = analyze_experiment(df, ExperimentConfig(
        primary=BIN, sequential=_obf(2, planned_sample_size=8000)))
    assert honest.decision is Decision.INCONCLUSIVE
    with pytest.raises(ValueError, match="not above"):
        analyze_experiment(df, ExperimentConfig(
            primary=BIN, sequential=_obf(4, planned_sample_size=8000)))


def test_without_a_planned_sample_size_the_assumption_is_stated():
    df = make_experiment(n=8000, lift=0.03).iloc[:4000]
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, sequential=_obf(4)))
    note = _diag(r, "sequential_information")
    assert note.passed and "not checked against the data" in note.message
    assert any("fixed before the experiment started" in a for a in r.assumptions)


def test_reusing_the_final_critical_value_at_every_look_inflates_the_error():
    b = sq.sequential_boundaries(5, 0.05, "obrien-fleming")
    lower, upper = sq.exit_probabilities([b.critical_values[-1]] * 5, b.information_fractions)
    assert sum(lower) + sum(upper) > 0.10  # more than double the nominal 5%


def test_a_look_that_can_never_stop_stays_inconclusive_without_crashing():
    df = make_experiment(n=2000, lift=0.08)
    design = SequentialDesign(method="obrien-fleming", planned_looks=3, current_look=1,
                              information_fractions=[0.001, 0.5, 1.0])
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, sequential=design))
    assert r.sequential.critical_value == float("inf")
    assert r.decision is Decision.INCONCLUSIVE and np.isfinite(r.primary.ci_low)
    assert "Continue to the next planned look" in " ".join(r.reasons)
    assert "inf" in render_markdown(r)


def test_cli_look_beyond_plan_and_bad_fractions(tmp_path, capsys):
    path = tmp_path / "exp.csv"
    make_experiment(n=2000).to_csv(path, index=False)
    base = ["analyze", str(path), "--metric", "converted", "--metric-type", "binary",
            "--sequential", "obrien-fleming"]
    for extra in (["--planned-looks", "3", "--look", "4"],
                  ["--planned-looks", "3", "--look", "1", "--info-fractions", "0.5,1"],
                  ["--planned-looks", "2", "--look", "1", "--info-fractions", "0.9,0.5"],
                  ["--planned-looks", "2", "--look", "2", "--planned-n", "100000"],
                  ["--planned-looks", "500", "--look", "1"]):
        assert main([*base, *extra]) == 1
        assert capsys.readouterr().err.startswith("error:")


# --- tiny or degenerate segments --------------------------------------------------------

def test_tiny_segments_are_skipped_not_tested():
    df = make_experiment(n=6000, lift=0.03)
    df.loc[df.index[:25], "segment"] = "smart-fridge"
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, segment_col="segment"))
    seg = r.segments
    assert [s.segment for s in seg.segments] == ["desktop", "mobile", "tablet"]
    assert [(k.segment, k.n_control + k.n_treatment) for k in seg.skipped] == [
        ("smart-fridge", 25)]
    assert "fewer than 30 units" in seg.skipped[0].reason
    # the family for the correction is the three analysed segments, not four
    raw = sorted(s.estimate.p_value for s in seg.segments)
    assert min(s.adjusted_p_value for s in seg.segments) == pytest.approx(min(1, raw[0] * 3))
    assert "not analysed" in render_markdown(r)


def test_segments_without_variation_or_without_units_are_skipped():
    df = make_experiment(n=6000, lift=0.03)
    df.loc[df["segment"] == "tablet", "converted"] = 0
    df.loc[df.index[:40], "segment"] = None
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, segment_col="segment"))
    assert {k.segment: k.reason for k in r.segments.skipped} == {
        "tablet": "no variation in the metric"}
    assert r.segments.units_without_segment == 40 and len(r.segments.segments) == 2
    assert "40 unit(s) without a segment value" in r.segments.message


@pytest.mark.parametrize("column, fragment", [
    ("user_id", "levels; exploratory cuts are limited to 30"),
    ("constant", "fewer than 2 levels"),
    ("variant", "no level of 'variant' has 30+ units per arm"),
    ("rare", "no level of 'rare' has 30+ units per arm"),
])
def test_unusable_segment_columns_are_reported_not_analysed(column, fragment):
    df = make_experiment(n=3000, lift=0.03).assign(constant="all")
    df["rare"] = np.where(df.index < 10, "a", np.where(df.index < 20, "b", None))
    plain = analyze_experiment(df, ExperimentConfig(primary=BIN))
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, segment_col=column))
    d = _diag(r, "segments_exploratory")
    assert r.segments is None and not d.assessed and d.passed and fragment in d.message
    assert (r.decision, r.evidence_quality, r.reasons) == (
        plain.decision, plain.evidence_quality, plain.reasons)
    assert "**N/A** `segments_exploratory`" in render_markdown(r)


def test_numeric_and_mixed_segment_labels():
    df = make_experiment(n=6000, lift=0.03)
    df["tier"] = (df["user_id"] % 3).astype(object)
    df.loc[df["tier"] == 2, "tier"] = "two"
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, segment_col="tier"))
    assert [s.segment for s in r.segments.segments] == ["0", "1", "two"]


def test_missing_segment_column_is_a_configuration_error():
    with pytest.raises(ValueError, match="missing required column"):
        analyze_experiment(make_experiment(n=500), ExperimentConfig(
            primary=BIN, segment_col="nope"))
    with pytest.raises(ValueError):
        ExperimentConfig(primary=BIN, segment_correction="sidak")  # type: ignore[arg-type]


# --- missing or unusable dates ----------------------------------------------------------

def test_missing_date_column_is_a_configuration_error():
    with pytest.raises(ValueError, match="missing required column"):
        analyze_experiment(make_experiment(n=500), ExperimentConfig(primary=BIN, date_col="when"))


@pytest.mark.parametrize("mutate, fragment", [
    (lambda d: d.assign(exposure_date=None), "holds no usable dates"),
    (lambda d: d.assign(exposure_date="03/04/2026"), "holds no usable dates"),
    (lambda d: d.assign(exposure_date="not a date"), "holds no usable dates"),
    (lambda d: d.assign(exposure_date=d["converted"] == 1), "holds no usable dates"),
    (lambda d: d.assign(exposure_date="2026-01-05"), "only 1 usable period(s)"),
    (lambda d: d.assign(exposure_date=np.where(d.index % 3 == 0, "2026-01-05", np.where(
        d.index % 3 == 1, "2026-01-06", "2026-01-07"))), "only 3 usable period(s)"),
    (lambda d: d.assign(exposure_date=pd.Timestamp("2026-01-05")
                        + pd.to_timedelta(d.index, unit="D")), "only 0 usable period(s)"),
])
def test_unusable_dates_are_reported_as_not_assessed(mutate, fragment):
    df = make_experiment(n=4000, lift=0.03)
    plain = analyze_experiment(df, ExperimentConfig(primary=BIN))
    r = analyze_experiment(mutate(df), ExperimentConfig(primary=BIN, date_col="exposure_date"))
    d = _diag(r, "novelty_effect")
    assert not d.assessed and d.passed and d.severity == "info" and fragment in d.message
    assert r.novelty.assessed is False and not r.novelty.decay_detected
    assert (r.decision, r.evidence_quality, r.primary) == (
        plain.decision, plain.evidence_quality, plain.primary)
    assert "**N/A** `novelty_effect`" in render_markdown(r)


def test_partly_missing_dates_are_counted_and_do_not_touch_the_main_analysis():
    df = make_scenario("novelty_decay")
    full = analyze_experiment(df, ExperimentConfig(primary=BIN, date_col="exposure_date"))
    holes = df.copy()
    holes.loc[holes.index % 20 == 0, "exposure_date"] = None
    holes.loc[holes.index % 20 == 1, "exposure_date"] = "13/01/2026"
    r = analyze_experiment(holes, ExperimentConfig(primary=BIN, date_col="exposure_date"))
    assert r.primary == full.primary  # undated rows still count for the effect estimate
    assert r.novelty.rows_without_date == 4000 and r.novelty.decay_detected
    assert "4000 row(s) without a usable date" in _diag(r, "novelty_effect").message


def test_date_formats_that_are_accepted():
    df = make_scenario("novelty_decay")
    ref = analyze_experiment(df, ExperimentConfig(primary=BIN, date_col="exposure_date"))
    as_ts = df.assign(exposure_date=pd.to_datetime(df["exposure_date"]))
    as_tz = df.assign(exposure_date=pd.to_datetime(df["exposure_date"]).dt.tz_localize("UTC"))
    as_iso_time = df.assign(exposure_date=df["exposure_date"] + "T09:30:00Z")
    as_day_number = df.assign(exposure_date=(pd.to_datetime(df["exposure_date"])
                                             - pd.Timestamp("2026-01-05")).dt.days + 100)
    for variant in (as_ts, as_tz, as_iso_time, as_day_number):
        r = analyze_experiment(variant, ExperimentConfig(primary=BIN, date_col="exposure_date"))
        assert r.novelty.slope == pytest.approx(ref.novelty.slope, rel=1e-12)
        assert [p.index for p in r.novelty.periods] == list(range(14))
    idx, names = period_index(pd.Series(["2026-01-05", "2026-01-13", None, "garbage"]), 7)
    assert idx.tolist()[:2] == [0.0, 7.0] and idx.isna().sum() == 2
    assert names == {0: "2026-01-05", 7: "2026-01-12"}
    assert period_index(pd.Series([3.0, 5.5, np.inf, np.nan]))[1] == {0: "day 0", 2: "day 2"}


def test_a_stray_far_future_date_cannot_fake_a_trend():
    df = make_experiment(n=14000, lift=0.02)
    ref = analyze_experiment(df, ExperimentConfig(primary=BIN, date_col="exposure_date"))
    typo = df.copy()
    typo.loc[typo.index[:20], "exposure_date"] = "2206-01-05"
    r = analyze_experiment(typo, ExperimentConfig(primary=BIN, date_col="exposure_date"))
    assert len(r.novelty.periods) == 14 and r.novelty.excluded_periods == 1
    assert r.novelty.decay_detected == ref.novelty.decay_detected
    assert max(p.index for p in r.novelty.periods) == 13


# --- hostile input ----------------------------------------------------------------------

def test_markup_in_column_names_and_labels_is_neutralised():
    df = make_experiment(n=4000, lift=0.04).rename(columns={
        "converted": "<script>alert(1)</script>", "segment": "seg|ment](http://evil)"})
    df["seg|ment](http://evil)"] = df["seg|ment](http://evil)"].replace(
        {"mobile": "<img src=x onerror=alert(1)>", "tablet": "a`b\nc"})
    r = analyze_experiment(df, ExperimentConfig(
        primary=MetricSpec(column="<script>alert(1)</script>", type="binary"),
        segment_col="seg|ment](http://evil)"))
    md = render_markdown(r, title="report <b>x</b>\n# injected heading")
    assert not re.search(r"(?<!\\)<", md)  # no unescaped tag opener anywhere
    assert "](http" not in md and "\n# injected heading" not in md
    assert all(line.count("|") - line.count("\\|") in (0, 7, 8) for line in md.splitlines()
               if line.startswith("|"))  # escaped pipes do not add table cells
    assert json.loads(r.model_dump_json())["primary"]["metric"] == "<script>alert(1)</script>"


def test_unicode_and_blank_labels():
    df = make_experiment(n=3000, lift=0.04)
    df["variant"] = df["variant"].map({"control": "", "treatment": "实验组"})
    df = df.rename(columns={"converted": "转化"})
    r = analyze_experiment(df, ExperimentConfig(
        primary=MetricSpec(column="转化", type="binary"), control_label="",
        treatment_label="实验组", segment_col="segment"))
    assert r.primary.n_control + r.primary.n_treatment == 3000
    assert "转化" in render_markdown(r)


def test_values_that_overflow_are_refused_rather_than_analysed():
    df = make_experiment(n=2000, revenue_effect=5.0)
    df.loc[df.index[0], "revenue"] = 1e300
    df.loc[df.index[1], "revenue"] = -1e300
    with pytest.raises(ValueError, match="too large for a variance"):
        analyze_experiment(df, ExperimentConfig(
            primary=MetricSpec(column="revenue", type="continuous")))
    users = aggregate_to_units(make_sessions(n_users=400), "user_id",
                               {"clicks": "sum", "impressions": "sum"})
    users["clicks"] = users["clicks"].astype(float)
    users.loc[users.index[:2], "clicks"] = 1e300
    with pytest.raises(ValueError, match="too large for a variance"):
        analyze_experiment(users, ExperimentConfig(primary=CTR))


def test_ratio_metrics_reject_impossible_denominators():
    users = aggregate_to_units(make_sessions(n_users=400), "user_id",
                               {"clicks": "sum", "impressions": "sum"})
    with pytest.raises(ValueError, match=">= 0"):
        analyze_experiment(users.assign(impressions=-users["impressions"]),
                           ExperimentConfig(primary=CTR))
    with pytest.raises(ValueError, match="undefined"):
        analyze_experiment(users.assign(impressions=0), ExperimentConfig(primary=CTR))
    with pytest.raises(ValueError, match="must be numeric"):
        analyze_experiment(users.assign(impressions="many"), ExperimentConfig(primary=CTR))
    with pytest.raises(ValueError, match="missing required column"):
        analyze_experiment(users.drop(columns=["impressions"]), ExperimentConfig(primary=CTR))
    for bad in ({"type": "ratio"}, {"type": "binary", "denominator": "impressions"}):
        with pytest.raises(ValueError):
            MetricSpec(column="clicks", **bad)
    with pytest.raises(ValueError):
        GuardrailSpec(column="clicks", type="ratio", margin=0.1)


def test_ratio_metric_with_missing_parts_reports_missing_data():
    users = aggregate_to_units(make_sessions(n_users=3000, seed=8), "user_id",
                               {"clicks": "sum", "impressions": "sum"})
    users["impressions"] = users["impressions"].astype(float)
    users.loc[users.index % 50 == 0, "impressions"] = np.nan
    r = analyze_experiment(users, ExperimentConfig(primary=CTR))
    d = _diag(r, "missing_data_clicks/impressions")
    assert d.severity == "warning" and d.passed
    assert r.primary.n_control + r.primary.n_treatment == 3000 - 60


@pytest.mark.parametrize("kwargs", [
    {"aa_relabels": 50}, {"aa_relabels": -1}, {"aa_relabels": 10**7}, {"date_bin_days": 0},
    {"date_bin_days": 400}, {"sequential": {"method": "obrien-fleming", "planned_looks": 2}},
])
def test_config_rejects_out_of_range_options(kwargs):
    with pytest.raises(ValueError):
        ExperimentConfig(primary=BIN, **kwargs)


def test_cli_survives_hostile_csv_for_new_options(tmp_path, capsys):
    path = tmp_path / "x.csv"
    path.write_text("variant,converted,when,seg\n" + "\n".join(
        f"{'control' if i % 2 else 'treatment'},{i % 3 == 0:d},=cmd|' /C calc'!A0,{'=1+1'}"
        for i in range(400)) + "\n", encoding="utf-8")
    assert main(["analyze", str(path), "--metric", "converted", "--metric-type", "binary",
                 "--date-col", "when", "--segment-col", "seg"]) == 0
    out = capsys.readouterr().out
    assert "**N/A** `novelty_effect`" in out and "**N/A** `segments_exploratory`" in out
    assert main(["analyze", str(path), "--metric", "converted", "--metric-type", "binary",
                 "--date-col", "missing"]) == 1
    assert main(["aa", str(path), "--metric", "when", "--metric-type", "continuous"]) == 1
    assert main(["aa", str(tmp_path / "none.csv"), "--metric", "x", "--metric-type",
                 "binary"]) == 1
    assert capsys.readouterr().err.count("error:") == 3
