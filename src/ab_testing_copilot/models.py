"""Typed result models shared across modules."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MetricType = Literal["binary", "continuous", "ratio"]
Correction = Literal["bonferroni", "holm", "benjamini-hochberg"]
Severity = Literal["info", "warning", "blocking"]
SpendingMethod = Literal["obrien-fleming", "pocock"]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SampleSizeResult(Model):
    metric_type: MetricType
    n_control: int
    n_treatment: int
    n_total: int
    alpha: float
    power: float
    absolute_mde: float
    relative_mde: float | None
    allocation_ratio: float
    assumptions: list[str]


class EffectEstimate(Model):
    metric: str
    metric_type: MetricType
    method: str
    n_control: int
    n_treatment: int
    control_value: float
    treatment_value: float
    absolute_effect: float
    ci_low: float
    ci_high: float
    relative_effect: float | None
    rel_ci_low: float | None
    rel_ci_high: float | None
    statistic: float
    p_value: float
    alpha: float
    warnings: list[str] = Field(default_factory=list)
    std_error: float | None = None


class Diagnostic(Model):
    """One validity check. ``assessed=False`` means the check could not be run."""

    name: str
    severity: Severity
    passed: bool
    message: str
    p_value: float | None = None
    assessed: bool = True


class Decision(StrEnum):
    SHIP = "Ship"
    DO_NOT_SHIP = "Do not ship"
    INCONCLUSIVE = "Inconclusive"


class GuardrailResult(Model):
    estimate: EffectEstimate
    status: Literal["pass", "fail", "uncertain"]
    margin: float
    message: str


class SequentialBoundaries(Model):
    """Critical values of a planned group-sequential design (two-sided, symmetric)."""

    method: SpendingMethod
    alpha: float
    information_fractions: list[float]
    critical_values: list[float]
    nominal_alpha: list[float]
    cumulative_alpha: list[float]
    assumptions: list[str]


class SequentialLook(Model):
    """The boundary that applies to the look being analysed."""

    method: SpendingMethod
    planned_looks: int
    current_look: int
    is_final: bool
    information_fraction: float
    observed_fraction: float | None
    critical_value: float
    nominal_alpha: float
    cumulative_alpha: float
    overall_alpha: float
    plan: SequentialBoundaries
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PeriodEffect(Model):
    """Treatment effect among the units of one time period."""

    index: int
    label: str
    n_control: int
    n_treatment: int
    effect: float
    std_error: float


class NoveltyResult(Model):
    """Trend of the treatment effect over time. A warning with its evidence, never proof."""

    assessed: bool
    reason: str | None = None
    alpha: float
    periods: list[PeriodEffect] = Field(default_factory=list)
    excluded_periods: int = 0
    rows_without_date: int = 0
    slope: float | None = None
    slope_std_error: float | None = None
    statistic: float | None = None
    dof: int | None = None
    p_value: float | None = None
    fitted_start: float | None = None
    fitted_end: float | None = None
    early_effect: float | None = None
    early_std_error: float | None = None
    late_effect: float | None = None
    late_std_error: float | None = None
    decay_detected: bool = False
    growth_detected: bool = False
    message: str


class SegmentEffect(Model):
    segment: str
    estimate: EffectEstimate
    adjusted_p_value: float
    significant_after_correction: bool
    simultaneous_ci_low: float
    simultaneous_ci_high: float


class SkippedSegment(Model):
    segment: str
    n_control: int
    n_treatment: int
    reason: str


class SegmentAnalysis(Model):
    """Per-segment effects. Always exploratory: it never feeds the decision."""

    exploratory: Literal[True] = True
    label: str = (
        "Exploratory - hypothesis-generating only. Segment results do not change the "
        "recommendation and need a new, pre-registered experiment to be confirmed."
    )
    segment_col: str
    correction: Correction
    alpha: float
    segments: list[SegmentEffect]
    skipped: list[SkippedSegment] = Field(default_factory=list)
    units_without_segment: int = 0
    pooled_effect: float | None = None
    q_statistic: float | None = None
    q_dof: int | None = None
    q_p_value: float | None = None
    i_squared: float | None = None
    heterogeneity_detected: bool = False
    message: str


class AAResult(Model):
    """Empirical false-positive rate of the analysis under random re-labelling of units."""

    analysis: str
    relabelled_unit: str
    n_units: int
    n_rows: int
    treatment_share: float
    n_relabels: int
    seed: int
    alpha: float
    false_positive_rate: float
    mc_standard_error: float
    ci_low: float
    ci_high: float
    binomial_p_value: float
    verdict: Literal["calibrated", "inflated", "conservative"]
    p_value_histogram: list[int]
    message: str


class DecisionReport(Model):
    decision: Decision
    evidence_quality: Literal["strong", "moderate", "weak", "invalid"]
    reasons: list[str]
    primary: EffectEstimate
    guardrails: list[GuardrailResult]
    diagnostics: list[Diagnostic]
    assumptions: list[str]
    effective_alpha: float
    sequential: SequentialLook | None = None
    novelty: NoveltyResult | None = None
    segments: SegmentAnalysis | None = None
    aa_check: AAResult | None = None


class SimulationResult(Model):
    name: str
    n_sims: int
    seed: int
    estimate: float
    mc_standard_error: float
    expected: float | None
    tolerance: float | None
    passed: bool | None
    details: dict[str, float] = Field(default_factory=dict)
