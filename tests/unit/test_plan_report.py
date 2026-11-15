"""Experiment plan (refuses to guess) and report rendering (escapes data-derived text)."""

import json
import math
import re

import pytest

from ab_testing_copilot import design
from ab_testing_copilot.cli import main
from ab_testing_copilot.decision import confidence_level
from ab_testing_copilot.plan import (
    REQUIRED,
    GuardrailPlan,
    PlanRequest,
    build_plan,
    plan_gaps,
    render_plan,
)
from ab_testing_copilot.report import render_boundaries, safe_text
from ab_testing_copilot.sequential import inflation_factor, sequential_boundaries

COMPLETE = [
    "--hypothesis", "A shorter checkout form raises conversion.", "--metric", "converted",
    "--metric-type", "binary", "--direction", "higher", "--baseline", "0.10", "--mde", "0.02",
    "--mde-scale", "absolute", "--alpha", "0.05", "--power", "0.8", "--treatment-share", "0.5",
    "--unit", "user_id", "--daily-units", "1000", "--traffic-share", "0.5",
    "--guardrail", "page_load_ms:continuous:lower:0.02", "--looks", "1",
]


def _without(flag):
    i = COMPLETE.index(flag)
    return COMPLETE[:i] + COMPLETE[i + 2:]


def _request(**overrides):
    base = dict(
        hypothesis="A shorter checkout form raises conversion.", metric="converted",
        metric_type="binary", higher_is_better=True, baseline=0.10, mde=0.02,
        mde_is_relative=False, alpha=0.05, power=0.8, treatment_share=0.5, unit="user_id",
        daily_units=1000, traffic_share=0.5,
        guardrails=[GuardrailPlan(name="page_load_ms", type="continuous",
                                  higher_is_better=False, margin=0.02)],
        looks=1)
    return PlanRequest(**{**base, **overrides})


def test_plan_with_nothing_supplied_lists_every_gap_and_computes_nothing(capsys):
    assert main(["plan"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "never guessed" in captured.err
    for flag in ("hypothesis", "metric", "metric-type", "direction", "baseline", "mde",
                 "mde-scale", "alpha", "power", "treatment-share", "unit", "daily-units",
                 "traffic-share", "looks", "guardrail"):
        assert f"  --{flag}: " in captured.err
    assert len(plan_gaps({})) == len(REQUIRED) + 1


@pytest.mark.parametrize("flag", [
    "--hypothesis", "--metric", "--metric-type", "--direction", "--baseline", "--mde",
    "--mde-scale", "--alpha", "--power", "--treatment-share", "--unit", "--daily-units",
    "--traffic-share", "--guardrail", "--looks",
])
def test_plan_refuses_when_any_single_input_is_missing(flag, capsys):
    assert main(["plan", *_without(flag)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and f"  {flag}: " in captured.err
    assert captured.err.count("\n  --") == 1  # only the one gap is reported


def test_plan_gaps_that_depend_on_other_answers(capsys):
    continuous = [a if a != "binary" else "continuous" for a in COMPLETE]
    assert main(["plan", *continuous]) == 1
    assert "--std-dev" in capsys.readouterr().err
    several = [a if a != "1" else "4" for a in COMPLETE]
    assert main(["plan", *several]) == 1
    assert "--sequential" in capsys.readouterr().err
    assert plan_gaps({"looks": 4, "sequential_method": "pocock", "guardrails": ["x"]}) == [
        g for g in plan_gaps({}) if not g.startswith(("looks", "guardrail"))]


def test_complete_fixed_horizon_plan(capsys):
    assert main(["plan", *COMPLETE, "--format", "json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert (plan["n_control"], plan["n_treatment"], plan["n_total"]) == (3841, 3841, 7682)
    assert plan["absolute_mde"] == 0.02 and plan["relative_mde"] == pytest.approx(0.2)
    assert plan["target_value"] == pytest.approx(0.12)
    assert plan["duration_days"] == 16 and plan["recommended_days"] == 21
    assert plan["inflation_factor"] is None and plan["boundaries"] is None
    assert plan["schedule"] == [] and len(plan["checklist"]) == 11
    assert any("16 days" in a and "21 days" in a for a in plan["assumptions"])
    assert "--sequential" not in plan["analysis_command"]
    assert plan["analysis_command"].startswith(
        "abcopilot analyze DATA.csv --metric converted --metric-type binary --guardrail "
        "page_load_ms:continuous:lower:0.02 --unit-col user_id --expected-share 0.5")

    assert main(["plan", *COMPLETE]) == 0
    md = capsys.readouterr().out
    for heading in ("# Experiment plan", "## Hypothesis", "## Metrics", "## Design",
                    "## Decision rule", "## Pre-registration checklist", "## Assumptions",
                    "## Analysis command"):
        assert heading in md
    assert "3,841 control + 3,841 treatment = 7,682 units" in md
    assert "Nothing was assumed on your behalf" in md and md.count("- [ ] ") == 11
    assert "Inconclusive is not 'no effect'" in md and "## Looks and boundaries" not in md


def test_plan_scales_direction_and_allocation():
    relative = build_plan(_request(mde=0.2, mde_is_relative=True))
    assert relative.absolute_mde == pytest.approx(0.02) and relative.n_control == 3841
    lower = build_plan(_request(higher_is_better=False))
    assert lower.target_value == pytest.approx(0.08)
    assert lower.n_control == design.sample_size_for_proportions(0.10, -0.02).n_control
    assert lower.n_control < 3841  # a drop from 10% to 8% has less variance than a rise to 12%
    assert "--lower-is-better" in lower.analysis_command
    uneven = build_plan(_request(treatment_share=0.2))
    ref = design.sample_size_for_proportions(0.10, 0.02, allocation_ratio=0.25)
    assert (uneven.n_control, uneven.n_treatment) == (ref.n_control, ref.n_treatment)
    assert "--expected-share 0.2" in uneven.analysis_command
    cont = build_plan(_request(metric_type="continuous", metric="revenue", baseline=40.0,
                               std_dev=25.0, mde=1.5))
    assert cont.n_control == design.sample_size_for_means(25.0, 1.5).n_control
    assert cont.relative_mde == pytest.approx(1.5 / 40)
    none = build_plan(_request(guardrails=[], no_guardrails_reason="pricing page only"))
    assert "none (pricing page only)" in " ".join(none.checklist)
    assert "Reason given: pricing page only" in render_plan(none)


def test_sequential_plan_inflates_the_sample_and_lists_the_looks(capsys):
    plan = build_plan(_request(looks=4, sequential_method="obrien-fleming"))
    factor = inflation_factor(sequential_boundaries(4, 0.05, "obrien-fleming"), 0.8)
    assert plan.inflation_factor == pytest.approx(factor) and 1.0 < factor < 1.03
    assert plan.n_control == math.ceil(3841 * factor) and plan.n_total == 2 * plan.n_control
    assert [s.look for s in plan.schedule] == [1, 2, 3, 4]
    assert plan.schedule[-1].units_total == plan.n_total
    assert plan.schedule[-1].day == plan.duration_days
    assert [s.critical_value for s in plan.schedule] == plan.boundaries.critical_values
    assert 0.5 < plan.expected_stop_fraction_if_mde_true < 1.0
    assert not any("single look" in a for a in plan.assumptions)
    assert any("no futility" in a.lower() for a in plan.assumptions)
    assert plan.analysis_command.endswith(
        f"--sequential obrien-fleming --planned-looks 4 --look LOOK --planned-n {plan.n_total}")
    md = render_plan(plan)
    assert "## Looks and boundaries" in md and "continue to the next planned look" in md
    assert main(["plan", *[a if a != "1" else "4" for a in COMPLETE], "--sequential",
                 "pocock"]) == 0
    assert "Pocock-type alpha spending" in capsys.readouterr().out


@pytest.mark.parametrize("extra, message", [
    (["--mde", "-0.02"], "greater than 0"),
    (["--power", "0.03"], "power must be larger than alpha"),
    (["--alpha", "1.5"], "less than 1"),
    (["--treatment-share", "1"], "less than 1"),
    (["--traffic-share", "0"], "greater than 0"),
    (["--daily-units", "-5"], "greater than 0"),
    (["--std-dev", "3"], "does not apply to a binary metric"),
    (["--sequential", "pocock"], "needs more than one planned look"),
    (["--no-guardrails", "none needed"], "not both"),
    (["--guardrail", "latency:continuous"], "all four parts"),
    (["--guardrail", "latency:continuous:lower:lots"], "margin must be a number"),
    (["--guardrail", "latency:weird:lower:0.1"], "guardrail 'latency:weird:lower:0.1': type"),
    (["--guardrail", "latency:binary:lower:-1"], "guardrail 'latency:binary:lower:-1': margin"),
    (["--baseline", "0.99"], "inside (0, 1)"),
    (["--baseline", "1.2"], "must lie inside (0, 1)"),
    (["--metric", "bad`name"], "control characters or backticks"),
    (["--unit", "user\nid"], "control characters or backticks"),
    (["--hypothesis", "   "], "must not be blank"),
    (["--looks", "0"], "greater than or equal to 1"),
])
def test_plan_rejects_incoherent_input(extra, message, capsys):
    assert main(["plan", *COMPLETE, *extra]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and message in captured.err


def test_plan_request_is_strict_and_writes_files(tmp_path, capsys):
    with pytest.raises(ValueError):
        PlanRequest(**{**_request().model_dump(), "surprise": 1})
    with pytest.raises(ValueError, match="inside"):
        _request(baseline=0.0)
    with pytest.raises(ValueError, match="relative MDE"):
        _request(metric_type="continuous", baseline=-1.0, std_dev=2.0, mde=0.1,
                 mde_is_relative=True)
    with pytest.raises(ValueError, match="keep baseline"):
        build_plan(_request(baseline=0.99))  # 0.99 + 0.02 is not a rate
    out = tmp_path / "plan.md"
    assert main(["plan", *COMPLETE, "--out", str(out)]) == 0
    assert out.read_text() + "\n" == capsys.readouterr().out  # print adds one newline


def test_plan_escapes_free_text():
    plan = build_plan(_request(hypothesis="<script>alert(1)</script> [x](http://evil) | y"))
    md = render_plan(plan)
    assert not re.search(r"(?<!\\)<", md) and "](http" not in md  # no unescaped tag or link
    assert "\\<script>alert(1)\\</script> [x]\\(http://evil) \\| y" in md
    quoted = build_plan(_request(metric="conv rate; rm -rf /"))
    assert "'conv rate; rm -rf /'" in quoted.analysis_command


@pytest.mark.parametrize("text, expected", [
    ("plain_name", "plain_name"), ("a|b", "a\\|b"), ("<b>x</b>", "\\<b>x\\</b>"),
    ("line1\nline2\ttab", "line1 line2 tab"), ("[t](http://x)", "[t]\\(http://x)"),
    ("![img](u)", "!\\[img]\\(u)"), ("back`tick", "back\\`tick"), ("a\\b", "a\\\\b"),
    (12.5, "12.5"), ("\x00\x1f", " "),
])
def test_safe_text(text, expected):
    assert safe_text(text) == expected


def test_boundary_table_and_confidence_labels():
    table = render_boundaries(sequential_boundaries(
        alpha=0.05, method="obrien-fleming", information_fractions=[0.001, 0.5, 1.0]), 2)
    assert "| 1 | 0.001 | inf | 0 | 0 |" in table and "| 2 (this look) |" in table
    assert confidence_level(0.05) == "95.0%" and confidence_level(0.01) == "99.0%"
    assert confidence_level(1.0777e-6) == "99.99989%"  # never rounds up to 100%
    assert confidence_level(1e-40) == "(1 - 1.0e-40)"
    for bad in (0.0, 1.0, -1.0):
        with pytest.raises(ValueError):
            confidence_level(bad)
