"""End-to-end analysis of a row-level experiment table."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from ab_testing_copilot.analysis import compare_means, compare_proportions, cuped_adjust
from ab_testing_copilot.decision import decide, evaluate_guardrail
from ab_testing_copilot.diagnostics import (
    covariate_balance_check,
    missing_data_check,
    outlier_check,
    peeking_check,
    srm_check,
)
from ab_testing_copilot.models import DecisionReport, Diagnostic, EffectEstimate, MetricType

log = logging.getLogger(__name__)


class MetricSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    type: MetricType
    higher_is_better: bool = True


class GuardrailSpec(MetricSpec):
    margin: float = Field(default=0.02, ge=0)


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_col: str = "variant"
    control_label: str = "control"
    treatment_label: str = "treatment"
    primary: MetricSpec
    guardrails: list[GuardrailSpec] = Field(default_factory=list)
    unit_col: str | None = None
    covariate_col: str | None = None
    expected_treatment_share: float = Field(default=0.5, gt=0, lt=1)
    alpha: float = Field(default=0.05, gt=0, lt=1)
    absolute_mde: float | None = None
    n_looks: int = Field(default=1, ge=1)
    require_guardrail_noninferiority: bool = True


def _estimate(
    c: pd.Series, t: pd.Series, spec: MetricSpec, alpha: float
) -> EffectEstimate:
    if spec.type == "binary":
        for arm, s in (("control", c), ("treatment", t)):
            if not s.isin([0, 1]).all():
                raise ValueError(
                    f"binary metric '{spec.column}' has values other than 0/1 in {arm}; "
                    "declare it as continuous or fix the data"
                )
        return compare_proportions(int(c.sum()), len(c), int(t.sum()), len(t), alpha, spec.column)
    return compare_means(c.to_numpy(float), t.to_numpy(float), alpha, spec.column)


def analyze_experiment(df: pd.DataFrame, config: ExperimentConfig) -> DecisionReport:
    """Run diagnostics, estimate effects and return a decision report.

    Raises ``ValueError`` for structurally unusable input (missing columns, empty arms,
    non-numeric metrics). Statistical validity problems are reported as diagnostics.
    """
    specs: list[MetricSpec] = [config.primary, *config.guardrails]
    needed = {config.variant_col, *(s.column for s in specs)}
    needed |= {c for c in (config.unit_col, config.covariate_col) if c}
    missing_cols = sorted(needed - set(df.columns))
    if missing_cols:
        raise ValueError(f"missing required column(s): {missing_cols}; found {list(df.columns)}")
    for col in [s.column for s in specs] + ([config.covariate_col] if config.covariate_col else []):
        if not pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]):
            raise ValueError(f"column '{col}' must be numeric, got dtype {df[col].dtype}")

    labels = [config.control_label, config.treatment_label]
    diags: list[Diagnostic] = []
    other = int((~df[config.variant_col].isin(labels)).sum())
    if other:
        diags.append(Diagnostic(
            name="unexpected_variants", severity="warning", passed=False,
            message=f"{other} row(s) carry a variant label outside {labels} and were ignored."))
    data = df[df[config.variant_col].isin(labels)]
    is_t = data[config.variant_col] == config.treatment_label
    ctrl, trt = data[~is_t], data[is_t]
    if len(ctrl) < 2 or len(trt) < 2:
        raise ValueError(
            f"each arm needs at least 2 rows (control={len(ctrl)}, treatment={len(trt)})")

    n_c, n_t = len(ctrl), len(trt)
    if config.unit_col:
        u = config.unit_col
        both = set(ctrl[u].dropna()) & set(trt[u].dropna())
        if both:
            diags.append(Diagnostic(
                name="contamination", severity="blocking", passed=False,
                message=f"{len(both)} unit(s) appear in both arms: assignment is contaminated."))
        dup = int(data.duplicated(subset=[u, config.variant_col]).sum())
        if dup:
            diags.append(Diagnostic(
                name="unit_of_analysis", severity="blocking", passed=False,
                message=(f"{dup} repeated row(s) per '{u}': rows are not independent, so standard "
                         "errors are understated. Aggregate to one row per randomised unit.")))
        n_c, n_t = int(ctrl[u].nunique()), int(trt[u].nunique())
    diags.append(srm_check(n_c, n_t, config.expected_treatment_share))

    alpha_primary = config.alpha / config.n_looks
    diags.append(peeking_check(config.n_looks, config.alpha))
    assumptions = [
        "Units were randomly assigned and analysed as assigned (intention to treat).",
        "One independent observation per randomised unit.",
        "Two-sided tests; guardrails are not corrected for multiplicity (conservative for harm).",
        "Segment or exploratory cuts are hypothesis-generating, not confirmatory.",
    ]

    estimates: list[EffectEstimate] = []
    for i, spec in enumerate(specs):
        mc, mt = int(ctrl[spec.column].isna().sum()), int(trt[spec.column].isna().sum())
        d = missing_data_check(mc, len(ctrl), mt, len(trt))
        if mc + mt:
            diags.append(d.model_copy(update={"name": f"missing_data_{spec.column}"}))
        c, t = ctrl[spec.column].dropna(), trt[spec.column].dropna()
        if len(c) < 2 or len(t) < 2:
            raise ValueError(f"metric '{spec.column}' has fewer than 2 non-missing rows in an arm")
        if np.isinf(c.to_numpy(float)).any() or np.isinf(t.to_numpy(float)).any():
            raise ValueError(f"metric '{spec.column}' contains infinite values")
        est = _estimate(c, t, spec, alpha_primary if i == 0 else config.alpha)
        if i == 0:
            if spec.type == "continuous":
                diags.append(outlier_check(c.to_numpy(float), "control"))
                diags.append(outlier_check(t.to_numpy(float), "treatment"))
            est = _maybe_cuped(est, ctrl, trt, spec, config, alpha_primary, diags, assumptions)
        estimates.append(est)

    guardrails = [
        evaluate_guardrail(e, g.higher_is_better, g.margin)
        for e, g in zip(estimates[1:], config.guardrails, strict=True)
    ]
    report = decide(
        estimates[0], guardrails, diags, config.primary.higher_is_better, config.absolute_mde,
        config.require_guardrail_noninferiority, assumptions,
    )
    log.info("decision=%s quality=%s", report.decision.value, report.evidence_quality)
    return report


def _maybe_cuped(
    est: EffectEstimate, ctrl: pd.DataFrame, trt: pd.DataFrame, spec: MetricSpec,
    config: ExperimentConfig, alpha: float, diags: list[Diagnostic], assumptions: list[str],
) -> EffectEstimate:
    cov = config.covariate_col
    if not cov:
        return est
    c = ctrl[[spec.column, cov]].dropna()
    t = trt[[spec.column, cov]].dropna()
    if len(c) < len(ctrl[spec.column].dropna()) or len(t) < len(trt[spec.column].dropna()):
        diags.append(Diagnostic(
            name="cuped", severity="warning", passed=False,
            message=f"Covariate '{cov}' has missing values; CUPED was skipped."))
        return est
    diags.append(covariate_balance_check(c[cov].to_numpy(float), t[cov].to_numpy(float)))
    yc, yt, theta, red = cuped_adjust(
        c[spec.column].to_numpy(float), c[cov].to_numpy(float),
        t[spec.column].to_numpy(float), t[cov].to_numpy(float))
    if red <= 0.01:
        diags.append(Diagnostic(
            name="cuped", severity="info", passed=True,
            message=f"CUPED variance reduction {red:.1%} is negligible; raw estimate reported."))
        return est
    adj = compare_means(yc, yt, alpha, spec.column)
    diags.append(Diagnostic(
        name="cuped", severity="info", passed=True,
        message=f"CUPED applied with '{cov}' (theta = {theta:.4g}, variance reduction {red:.1%})."))
    assumptions.append(f"'{cov}' was measured before assignment and is unaffected by treatment.")
    return adj.model_copy(update={
        "metric_type": spec.type,
        "method": "CUPED-adjusted Welch t test; delta-method relative CI",
        "warnings": [w for w in adj.warnings if "zero variance" in w] + est.warnings,
    })
