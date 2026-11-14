"""Typed result models shared across modules."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MetricType = Literal["binary", "continuous"]
Severity = Literal["info", "warning", "blocking"]


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


class Diagnostic(Model):
    name: str
    severity: Severity
    passed: bool
    message: str
    p_value: float | None = None


class Decision(StrEnum):
    SHIP = "Ship"
    DO_NOT_SHIP = "Do not ship"
    INCONCLUSIVE = "Inconclusive"


class GuardrailResult(Model):
    estimate: EffectEstimate
    status: Literal["pass", "fail", "uncertain"]
    margin: float
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
