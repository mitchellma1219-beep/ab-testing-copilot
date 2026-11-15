"""Experiment plan: a pre-registration document computed from explicit inputs only.

The planner never fills a gap with a default. Every substantive choice (hypothesis, metric,
direction, baseline, MDE, alpha, power, allocation, traffic, guardrails, number of looks) must
be stated; :func:`plan_gaps` lists what is missing so the caller can ask for it.
"""

from __future__ import annotations

import math
import re
import shlex
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ab_testing_copilot import design
from ab_testing_copilot.decision import confidence_level
from ab_testing_copilot.models import Model, SampleSizeResult, SequentialBoundaries, SpendingMethod
from ab_testing_copilot.report import safe_text
from ab_testing_copilot.sequential import (
    METHOD_LABELS,
    expected_information,
    inflation_factor,
    required_drift,
    sequential_assumptions,
    sequential_boundaries,
)

REQUIRED: dict[str, str] = {
    "hypothesis": "what change is expected to move which metric, and why",
    "metric": "the single primary metric the decision rests on",
    "metric_type": "binary or continuous: it decides the test and the sample-size formula",
    "direction": "whether higher or lower values of the primary metric are better",
    "baseline": "the current rate (binary) or mean (continuous) of the primary metric",
    "mde": "the smallest effect worth detecting; it drives the sample size",
    "mde_scale": "absolute (metric units) or relative (share of the baseline): 0.02 means "
                 "very different things on the two scales",
    "alpha": "the false-positive rate you accept",
    "power": "the chance of detecting an effect of the size of the MDE",
    "treatment_share": "the share of enrolled units assigned to treatment",
    "unit": "the unit that is randomised (for example user_id); it is the unit of analysis",
    "daily_units": "new eligible units per day; without it no duration can be stated",
    "traffic_share": "the share of eligible units enrolled in the experiment",
    "looks": "how many times results will be analysed (1 = a single fixed-horizon analysis)",
}


_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f`]")


def _check_name(value: str, what: str) -> None:
    if not value.strip() or _UNSAFE_NAME.search(value):
        raise ValueError(f"{what} must be non-empty text without control characters or backticks")


class GuardrailPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    type: Literal["binary", "continuous", "ratio"]
    higher_is_better: bool
    margin: float = Field(ge=0)

    @model_validator(mode="after")
    def _name_is_plain(self) -> GuardrailPlan:
        _check_name(self.name, "guardrail name")
        return self


class PlanRequest(BaseModel):
    """All inputs of a plan. Nothing here has a substantive default."""

    model_config = ConfigDict(extra="forbid")
    hypothesis: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    metric_type: Literal["binary", "continuous"]
    higher_is_better: bool
    baseline: float
    std_dev: float | None = None
    mde: float = Field(gt=0)
    mde_is_relative: bool
    alpha: float = Field(gt=0, lt=1)
    power: float = Field(gt=0, lt=1)
    treatment_share: float = Field(gt=0, lt=1)
    unit: str = Field(min_length=1)
    daily_units: float = Field(gt=0)
    traffic_share: float = Field(gt=0, le=1)
    guardrails: list[GuardrailPlan]
    no_guardrails_reason: str | None = None
    looks: int = Field(ge=1, le=100)
    sequential_method: SpendingMethod | None = None

    @model_validator(mode="after")
    def _coherent(self) -> PlanRequest:
        _check_name(self.metric, "metric")
        _check_name(self.unit, "unit")
        if not self.hypothesis.strip():
            raise ValueError("hypothesis must not be blank")
        if not math.isfinite(self.baseline):
            raise ValueError("baseline must be finite")
        if self.std_dev is not None and not self.std_dev > 0:
            raise ValueError("std_dev must be > 0")
        if self.metric_type == "binary" and not 0 < self.baseline < 1:
            raise ValueError("the baseline of a binary metric must lie inside (0, 1)")
        if self.mde_is_relative and not self.baseline > 0:
            raise ValueError("a relative MDE needs a baseline > 0")
        if self.metric_type == "continuous" and self.std_dev is None:
            raise ValueError("a continuous metric needs its standard deviation (std_dev)")
        if self.metric_type == "binary" and self.std_dev is not None:
            raise ValueError("std_dev does not apply to a binary metric")
        if not self.guardrails and not (self.no_guardrails_reason or "").strip():
            raise ValueError(
                "declare at least one guardrail, or state why none applies "
                "(no_guardrails_reason)")
        if self.guardrails and self.no_guardrails_reason:
            raise ValueError("give guardrails or a reason for having none, not both")
        if self.looks > 1 and self.sequential_method is None:
            raise ValueError(
                "more than one look needs a sequential method (obrien-fleming or pocock); "
                "looking repeatedly at a fixed-horizon test inflates false positives")
        if self.looks == 1 and self.sequential_method is not None:
            raise ValueError("a sequential method needs more than one planned look")
        if not self.power > self.alpha:
            raise ValueError("power must be larger than alpha")
        return self


class PlannedLook(Model):
    look: int
    information_fraction: float
    units_total: int
    day: int
    critical_value: float
    nominal_alpha: float
    cumulative_alpha: float


class ExperimentPlan(Model):
    request: PlanRequest
    absolute_mde: float
    relative_mde: float | None
    target_value: float
    fixed_horizon: SampleSizeResult
    n_control: int
    n_treatment: int
    n_total: int
    inflation_factor: float | None
    expected_stop_fraction_if_mde_true: float | None
    boundaries: SequentialBoundaries | None
    schedule: list[PlannedLook]
    duration_days: int
    recommended_days: int
    decision_rule: list[str]
    checklist: list[str]
    assumptions: list[str]
    analysis_command: str


def plan_gaps(values: Mapping[str, object]) -> list[str]:
    """Human-readable list of the required plan inputs that are absent from ``values``."""
    gaps = [f"{key.replace('_', '-')}: {why}" for key, why in REQUIRED.items()
            if values.get(key) is None]
    if values.get("metric_type") == "continuous" and values.get("std_dev") is None:
        gaps.append("std-dev: the standard deviation of a continuous primary metric")
    if not values.get("guardrails") and not values.get("no_guardrails_reason"):
        gaps.append("guardrail: at least one guardrail metric with its margin, or "
                    "no-guardrails with the reason why none applies")
    looks = values.get("looks")
    if isinstance(looks, int) and looks > 1 and values.get("sequential_method") is None:
        gaps.append("sequential: the alpha-spending method (obrien-fleming or pocock) for "
                    "more than one look")
    return gaps


def build_plan(request: PlanRequest) -> ExperimentPlan:
    """Compute sample size, duration, boundaries, decision rule and checklist for a request."""
    r = request
    sign = 1.0 if r.higher_is_better else -1.0
    absolute = r.mde * r.baseline if r.mde_is_relative else r.mde
    ratio = r.treatment_share / (1 - r.treatment_share)
    if r.metric_type == "binary":
        fixed = design.sample_size_for_proportions(r.baseline, sign * absolute, r.alpha, r.power,
                                                   ratio)
    else:
        fixed = design.sample_size_for_means(float(r.std_dev or 0.0), absolute, r.alpha, r.power,
                                             ratio, r.baseline)
    bounds: SequentialBoundaries | None = None
    inflation: float | None = None
    stop_fraction: float | None = None
    n_c, n_t = fixed.n_control, fixed.n_treatment
    if r.sequential_method is not None:
        bounds = sequential_boundaries(r.looks, r.alpha, r.sequential_method)
        inflation = inflation_factor(bounds, r.power)
        stop_fraction = expected_information(
            bounds.critical_values, bounds.information_fractions, required_drift(bounds, r.power))
        n_c = math.ceil(fixed.n_control * inflation)
        n_t = math.ceil(n_c * ratio)
    n_total = n_c + n_t
    days = design.duration_days(n_total, r.daily_units, r.traffic_share)
    recommended = 7 * math.ceil(days / 7)
    per_day = r.daily_units * r.traffic_share
    schedule: list[PlannedLook] = []
    if bounds is not None:
        for k, (t, c, a, spent) in enumerate(zip(
                bounds.information_fractions, bounds.critical_values, bounds.nominal_alpha,
                bounds.cumulative_alpha, strict=True), 1):
            units = math.ceil(t * n_total)
            schedule.append(PlannedLook(look=k, information_fraction=t, units_total=units,
                                        day=math.ceil(units / per_day), critical_value=c,
                                        nominal_alpha=a, cumulative_alpha=spent))
    return ExperimentPlan(
        request=r, absolute_mde=absolute,
        relative_mde=absolute / r.baseline if r.baseline > 0 else None,
        target_value=r.baseline + sign * absolute, fixed_horizon=fixed,
        n_control=n_c, n_treatment=n_t, n_total=n_total, inflation_factor=inflation,
        expected_stop_fraction_if_mde_true=stop_fraction, boundaries=bounds, schedule=schedule,
        duration_days=days, recommended_days=recommended,
        decision_rule=_decision_rule(r, absolute, bounds),
        checklist=_checklist(r, n_total, recommended, bounds),
        assumptions=_assumptions(r, fixed, recommended, days),
        analysis_command=_command(r, absolute, n_total),
    )


def _decision_rule(r: PlanRequest, absolute: float, b: SequentialBoundaries | None) -> list[str]:
    better = "above" if r.higher_is_better else "below"
    worse = "below" if r.higher_is_better else "above"
    level = confidence_level(r.alpha)
    if b is None:
        interval = f"the {level} confidence interval of the effect on {r.metric}"
        when = "at the single planned analysis"
    else:
        interval = (f"the repeated confidence interval of the effect on {r.metric} (critical "
                    "value of the look, see the boundary table)")
        when = f"at any of the {r.looks} planned looks"
    rule = [
        "Validity first: a sample ratio mismatch (p below 0.001), units in both arms, repeated "
        "rows per unit, differential missing data or a pre-period imbalance make the result "
        "Inconclusive, whatever the effect looks like.",
        f"Ship if, {when}, {interval} lies entirely {better} zero and every guardrail rules "
        "out harm beyond its margin.",
        f"Do not ship if {interval} lies entirely {worse} zero, or any guardrail shows a "
        "statistically significant regression.",
    ]
    if b is None:
        rule.append(
            f"Otherwise Inconclusive. If the interval excludes improvements of {absolute:.4g} "
            "(the MDE), a worthwhile win is ruled out; if it still includes the MDE, the test "
            "was underpowered. Inconclusive is not 'no effect'.")
    else:
        rule.append(
            "Otherwise continue to the next planned look; after the final look the result is "
            "Inconclusive. There is no futility rule: do not stop early for a flat result.")
    rule.append("Segment cuts and a novelty check are exploratory or advisory. They never "
                "change the recommendation.")
    return rule


def _checklist(r: PlanRequest, n_total: int, days: int,
               b: SequentialBoundaries | None) -> list[str]:
    looks = ("one analysis, at the end" if b is None else
             f"{r.looks} looks with {METHOD_LABELS[b.method]} alpha spending, at the listed "
             "sample sizes")
    items = [
        f"Hypothesis, primary metric ({r.metric}) and direction are written down before launch.",
        f"The randomisation unit is {r.unit}; the analysis table has one row per {r.unit}.",
        f"Allocation is {r.treatment_share:.0%} treatment / {1 - r.treatment_share:.0%} "
        "control, assigned at random and logged at assignment.",
        f"Sample size {n_total:,} units and run length {days} days are fixed in advance; the "
        "experiment is not stopped because a result looks significant.",
        f"Analysis schedule: {looks}. No other looks at the primary metric.",
        "Guardrails and their margins are fixed: "
        + ("; ".join(f"{g.name} ({'higher' if g.higher_is_better else 'lower'} is better, "
                     f"margin {g.margin:.3g})" for g in r.guardrails)
           if r.guardrails else f"none ({r.no_guardrails_reason})") + ".",
        "Outlier handling (for example a winsorisation level) and any pre-period covariate "
        "for CUPED are chosen now, not after seeing results.",
        "Exposure logging has been checked with an A/A run or an SRM check on a dry run.",
        "Segments to be explored are listed now and will be reported as exploratory.",
        "Start and end dates cover whole weeks; holidays or launches that overlap are noted.",
        "An owner is named for the decision, and what happens for each outcome (Ship, Do not "
        "ship, Inconclusive) is agreed.",
    ]
    return items


def _assumptions(r: PlanRequest, fixed: SampleSizeResult, recommended: int,
                 days: int) -> list[str]:
    out = (sequential_assumptions(fixed.assumptions) if r.sequential_method is not None
           else list(fixed.assumptions))
    out.append(
        f"Traffic: a constant {r.daily_units:,.0f} new eligible {r.unit} per day, of which "
        f"{r.traffic_share:.0%} are enrolled, each counted once. Returning units do not add "
        "sample.")
    if recommended != days:
        out.append(
            f"The arithmetic minimum is {days} days; {recommended} days are recommended so "
            "that every weekday is covered equally.")
    out.append("The baseline and (for continuous metrics) the standard deviation are the "
               "values supplied; if they are wrong, so are the sample size and the power.")
    if r.sequential_method is not None:
        out.append("Looks are equally spaced in sample size. If a look happens at a different "
                   "size, pass the planned total to the analysis so alpha is spent for the "
                   "information actually collected.")
    return out


def _command(r: PlanRequest, absolute: float, n_total: int) -> str:
    parts = ["abcopilot", "analyze", "DATA.csv", "--metric", r.metric, "--metric-type",
             r.metric_type]
    if not r.higher_is_better:
        parts.append("--lower-is-better")
    for g in r.guardrails:
        parts += ["--guardrail", f"{g.name}:{g.type}:"
                  f"{'higher' if g.higher_is_better else 'lower'}:{g.margin:g}"]
    parts += ["--unit-col", r.unit, "--expected-share", f"{r.treatment_share:g}",
              "--alpha", f"{r.alpha:g}", "--mde", f"{absolute:g}"]
    if r.sequential_method is not None:
        parts += ["--sequential", r.sequential_method, "--planned-looks", str(r.looks),
                  "--look", "LOOK", "--planned-n", str(n_total)]
    return " ".join(shlex.quote(p) for p in parts)


def render_plan(plan: ExperimentPlan) -> str:
    """Markdown pre-registration document."""
    r = plan.request
    rel = "n/a" if plan.relative_mde is None else f"{plan.relative_mde:.2%}"
    lines = [
        "# Experiment plan", "",
        "Every number below follows from the inputs that were supplied. Nothing was assumed "
        "on your behalf.", "",
        "## Hypothesis", "", safe_text(r.hypothesis), "",
        "## Metrics", "",
        f"- **Primary metric:** {safe_text(r.metric)} ({r.metric_type}), "
        f"{'higher' if r.higher_is_better else 'lower'} is better.",
        f"- **Baseline:** {r.baseline:g}"
        + (f" (standard deviation {r.std_dev:g})" if r.std_dev is not None else "") + ".",
        f"- **Minimum detectable effect:** {plan.absolute_mde:.4g} absolute ({rel} relative), "
        f"i.e. from {r.baseline:g} to {plan.target_value:g}.",
    ]
    if r.guardrails:
        lines += [f"- **Guardrail:** {safe_text(g.name)} ({g.type}), "
                  f"{'higher' if g.higher_is_better else 'lower'} is better; tolerated relative "
                  f"harm {g.margin:.3g}." for g in r.guardrails]
    else:
        lines.append(f"- **Guardrails:** none. Reason given: {safe_text(r.no_guardrails_reason)}")
    lines += [
        "", "## Design", "",
        f"- **Randomisation unit:** {safe_text(r.unit)}.",
        f"- **Allocation:** {r.treatment_share:.1%} treatment, {1 - r.treatment_share:.1%} "
        "control.",
        f"- **Alpha:** {r.alpha:g} (two-sided). **Power:** {r.power:g}.",
        f"- **Sample size:** {plan.n_control:,} control + {plan.n_treatment:,} treatment = "
        f"{plan.n_total:,} units.",
    ]
    if plan.inflation_factor is not None and plan.boundaries is not None:
        lines += [
            f"- **Sequential design:** {r.looks} looks, "
            f"{METHOD_LABELS[plan.boundaries.method]} alpha spending. The maximum sample is "
            f"{plan.inflation_factor:.4f} times the fixed-horizon size "
            f"({plan.fixed_horizon.n_total:,}). If the true effect equals the MDE, the "
            f"experiment stops on average at {plan.expected_stop_fraction_if_mde_true:.0%} of "
            "the maximum.",
        ]
    lines += [
        f"- **Duration:** {plan.duration_days} days at the stated traffic; run "
        f"{plan.recommended_days} days to cover whole weeks.", "",
    ]
    if plan.boundaries is not None:
        lines += ["## Looks and boundaries", "",
                  "| Look | Information fraction | Units (total) | Day | Critical value (abs z) "
                  "| Nominal two-sided alpha | Cumulative alpha spent |",
                  "|---|---|---|---|---|---|---|"]
        lines += [f"| {s.look} | {s.information_fraction:.3f} | {s.units_total:,} | {s.day} | "
                  f"{s.critical_value:.4f} | {s.nominal_alpha:.3g} | {s.cumulative_alpha:.3g} |"
                  for s in plan.schedule]
        lines.append("")
    lines += ["## Decision rule", "", *[f"{i}. {safe_text(x)}"
                                        for i, x in enumerate(plan.decision_rule, 1)], "",
              "## Pre-registration checklist", "",
              *[f"- [ ] {safe_text(x)}" for x in plan.checklist], "",
              "## Assumptions", "", *[f"- {safe_text(x)}" for x in plan.assumptions], "",
              "## Analysis command", "", "```", plan.analysis_command, "```", ""]
    return "\n".join(lines)
