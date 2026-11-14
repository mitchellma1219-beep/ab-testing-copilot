"""End-to-end analysis of a row-level experiment table."""

from __future__ import annotations

import logging
import sys
from typing import NamedTuple, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ab_testing_copilot import heterogeneity, novelty
from ab_testing_copilot.aa import MAX_RELABELS, MIN_RELABELS, aa_check, aa_diagnostic
from ab_testing_copilot.analysis import (
    compare_means,
    compare_proportions,
    compare_ratios,
    cuped_adjust,
)
from ab_testing_copilot.decision import decide, evaluate_guardrail
from ab_testing_copilot.diagnostics import (
    covariate_balance_check,
    missing_data_check,
    outlier_check,
    peeking_check,
    srm_check,
)
from ab_testing_copilot.models import (
    AAResult,
    Correction,
    DecisionReport,
    Diagnostic,
    EffectEstimate,
    MetricType,
    NoveltyResult,
    PeriodEffect,
    SegmentAnalysis,
    SequentialLook,
    SkippedSegment,
)
from ab_testing_copilot.sequential import (
    ASSUMPTIONS as SEQUENTIAL_ASSUMPTIONS,
)
from ab_testing_copilot.sequential import (
    METHOD_LABELS,
    SequentialDesign,
    sequential_look,
)

log = logging.getLogger(__name__)


class MetricSpec(BaseModel):
    """A metric column. ``type='ratio'`` means ``sum(column) / sum(denominator)`` over units."""

    model_config = ConfigDict(extra="forbid")
    column: str
    type: MetricType
    higher_is_better: bool = True
    denominator: str | None = None

    @model_validator(mode="after")
    def _denominator_matches_type(self) -> MetricSpec:
        if self.type == "ratio" and not self.denominator:
            raise ValueError("a ratio metric needs a denominator column")
        if self.type != "ratio" and self.denominator:
            raise ValueError("denominator is only valid for type='ratio'")
        return self

    @property
    def name(self) -> str:
        return f"{self.column}/{self.denominator}" if self.denominator else self.column

    @property
    def columns(self) -> list[str]:
        return [self.column, self.denominator] if self.denominator else [self.column]


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
    sequential: SequentialDesign | None = None
    date_col: str | None = None
    date_bin_days: int = Field(default=1, ge=1, le=28)
    segment_col: str | None = None
    segment_correction: Correction = "holm"
    aa_relabels: int = Field(default=0, ge=0, le=MAX_RELABELS)
    seed: int = 0

    @model_validator(mode="after")
    def _one_way_to_look(self) -> ExperimentConfig:
        if self.sequential is not None and self.n_looks > 1:
            raise ValueError(
                "declare either a pre-registered sequential design or unplanned looks "
                "(n_looks), not both. If looks were taken outside the plan, the sequential "
                "boundary no longer controls the error rate: drop the design and set n_looks "
                "to the total number of looks")
        if 0 < self.aa_relabels < MIN_RELABELS:
            raise ValueError(f"aa_relabels must be 0 (off) or at least {MIN_RELABELS}")
        return self


class _Frames(NamedTuple):
    control: pd.DataFrame
    treatment: pd.DataFrame
    missing_control: int
    missing_treatment: int


def _estimate(c: pd.DataFrame, t: pd.DataFrame, spec: MetricSpec, alpha: float) -> EffectEstimate:
    """Effect of ``spec`` between two frames that hold no missing metric values."""
    if spec.type == "ratio" and spec.denominator:
        return compare_ratios(
            c[spec.column].to_numpy(float), c[spec.denominator].to_numpy(float),
            t[spec.column].to_numpy(float), t[spec.denominator].to_numpy(float),
            alpha, spec.name)
    yc, yt = c[spec.column], t[spec.column]
    if spec.type == "binary":
        for arm, s in (("control", yc), ("treatment", yt)):
            if not s.isin([0, 1]).all():
                raise ValueError(
                    f"binary metric '{spec.column}' has values other than 0/1 in {arm}; "
                    "declare it as continuous or fix the data"
                )
        return compare_proportions(int(yc.sum()), len(yc), int(yt.sum()), len(yt), alpha,
                                   spec.column)
    return compare_means(yc.to_numpy(float), yt.to_numpy(float), alpha, spec.column)


def _frames(ctrl: pd.DataFrame, trt: pd.DataFrame, spec: MetricSpec) -> _Frames:
    cols = spec.columns
    c, t = ctrl.dropna(subset=cols), trt.dropna(subset=cols)
    return _Frames(c, t, len(ctrl) - len(c), len(trt) - len(t))


def analyze_experiment(df: pd.DataFrame, config: ExperimentConfig) -> DecisionReport:
    """Run diagnostics, estimate effects and return a decision report.

    Raises ``ValueError`` for structurally unusable input (missing columns, empty arms,
    non-numeric metrics). Statistical validity problems are reported as diagnostics.
    """
    specs: list[MetricSpec] = [config.primary, *config.guardrails]
    metric_cols = list(dict.fromkeys(col for s in specs for col in s.columns))
    optional = (config.unit_col, config.covariate_col, config.date_col, config.segment_col)
    needed = {config.variant_col, *metric_cols} | {c for c in optional if c}
    missing_cols = sorted(needed - set(df.columns))
    if missing_cols:
        raise ValueError(f"missing required column(s): {missing_cols}; found {list(df.columns)}")
    for col in metric_cols + ([config.covariate_col] if config.covariate_col else []):
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
    repeated_units = False
    if config.unit_col:
        u = config.unit_col
        both = set(ctrl[u].dropna()) & set(trt[u].dropna())
        if both:
            diags.append(Diagnostic(
                name="contamination", severity="blocking", passed=False,
                message=f"{len(both)} unit(s) appear in both arms: assignment is contaminated."))
        dup = int(data.duplicated(subset=[u, config.variant_col]).sum())
        if dup:
            repeated_units = True
            diags.append(Diagnostic(
                name="unit_of_analysis", severity="blocking", passed=False,
                message=(f"{dup} repeated row(s) per '{u}': rows are not independent, so standard "
                         "errors are understated. Aggregate to one row per randomised unit.")))
        n_c, n_t = int(ctrl[u].nunique()), int(trt[u].nunique())
    diags.append(srm_check(n_c, n_t, config.expected_treatment_share))

    assumptions = [
        "Units were randomly assigned and analysed as assigned (intention to treat).",
        "One independent observation per randomised unit.",
        "Two-sided tests; guardrails are not corrected for multiplicity (conservative for harm).",
        "Segment or exploratory cuts are hypothesis-generating, not confirmatory.",
    ]

    frames = [_frames(ctrl, trt, spec) for spec in specs]
    for spec, fr in zip(specs, frames, strict=True):
        if len(fr.control) < 2 or len(fr.treatment) < 2:
            raise ValueError(f"metric '{spec.name}' has fewer than 2 non-missing rows in an arm")
        for col in spec.columns:
            if (np.isinf(fr.control[col].to_numpy(float)).any()
                    or np.isinf(fr.treatment[col].to_numpy(float)).any()):
                raise ValueError(f"metric '{col}' contains infinite values")

    look: SequentialLook | None = None
    if config.sequential is not None:
        n_observed = len(frames[0].control) + len(frames[0].treatment)
        look = sequential_look(config.sequential, config.alpha, n_observed)
        alpha_look = max(look.nominal_alpha, sys.float_info.min)
        diags.extend(_sequential_diagnostics(look))
        assumptions.extend(SEQUENTIAL_ASSUMPTIONS)
        assumptions.append(
            "Guardrail intervals use the same sequential critical value as the primary metric, "
            "so early looks under an O'Brien-Fleming-type boundary are insensitive to moderate "
            "harm.")
    else:
        alpha_look = config.alpha / config.n_looks
        diags.append(peeking_check(config.n_looks, config.alpha))
        if config.n_looks > 1:
            assumptions.append(
                "Unplanned looks: a guardrail regression is still flagged at the unadjusted "
                "level, but harm beyond the margin must be ruled out at the Bonferroni level.")

    estimates: list[EffectEstimate] = []
    strict: list[EffectEstimate | None] = []
    for i, (spec, fr) in enumerate(zip(specs, frames, strict=True)):
        if fr.missing_control + fr.missing_treatment:
            d = missing_data_check(fr.missing_control, len(ctrl), fr.missing_treatment, len(trt))
            diags.append(d.model_copy(update={"name": f"missing_data_{spec.name}"}))
        if i == 0:
            est = _estimate(fr.control, fr.treatment, spec, alpha_look)
            if spec.type != "binary":
                diags.append(outlier_check(fr.control[spec.column].to_numpy(float), "control"))
                diags.append(outlier_check(fr.treatment[spec.column].to_numpy(float), "treatment"))
            est = _maybe_cuped(est, ctrl, trt, spec, config, alpha_look, diags, assumptions)
            strict.append(None)
        elif look is None and config.n_looks > 1:
            est = _estimate(fr.control, fr.treatment, spec, config.alpha)
            strict.append(_estimate(fr.control, fr.treatment, spec, alpha_look))
        else:
            est = _estimate(fr.control, fr.treatment, spec, alpha_look)
            strict.append(None)
        estimates.append(est)

    novelty_result: NoveltyResult | None = None
    if config.date_col:
        novelty_result = _novelty(frames[0], config, config.date_col, repeated_units)
        diags.append(novelty.novelty_diagnostic(novelty_result))
    segments: SegmentAnalysis | None = None
    if config.segment_col:
        segments, reason = _segments(frames[0], config, config.segment_col)
        diags.append(heterogeneity.segment_diagnostic(segments, reason))
    aa: AAResult | None = None
    if config.aa_relabels:
        aa = _aa(frames[0], config)
        diags.append(aa_diagnostic(aa))

    guardrails = [
        evaluate_guardrail(e, g.higher_is_better, g.margin, s)
        for e, s, g in zip(estimates[1:], strict[1:], config.guardrails, strict=True)
    ]
    report = decide(
        estimates[0], guardrails, diags, config.primary.higher_is_better, config.absolute_mde,
        config.require_guardrail_noninferiority, assumptions, look,
    )
    log.info("decision=%s quality=%s", report.decision.value, report.evidence_quality)
    return report.model_copy(update={
        "novelty": novelty_result, "segments": segments, "aa_check": aa})


def _sequential_diagnostics(look: SequentialLook) -> list[Diagnostic]:
    label = METHOD_LABELS[look.method]
    final = " (final analysis)" if look.is_final else ""
    out = [Diagnostic(
        name="sequential_design", severity="info", passed=True,
        message=(f"Pre-registered {label} group-sequential design, look {look.current_look} of "
                 f"{look.planned_looks}{final} at information fraction "
                 f"{look.information_fraction:.3f}: significance needs an absolute z of at "
                 f"least {look.critical_value:.4f} (nominal two-sided level "
                 f"{look.nominal_alpha:.3g}); "
                 f"alpha spent so far {look.cumulative_alpha:.3g} of {look.overall_alpha:.3g}."))]
    out.extend(Diagnostic(name="sequential_information", severity="info", passed=True,
                          message=note) for note in look.notes)
    out.extend(Diagnostic(name="sequential_sample", severity="warning", passed=False,
                          message=note) for note in look.warnings)
    return out


def _maybe_cuped(
    est: EffectEstimate, ctrl: pd.DataFrame, trt: pd.DataFrame, spec: MetricSpec,
    config: ExperimentConfig, alpha: float, diags: list[Diagnostic], assumptions: list[str],
) -> EffectEstimate:
    cov = config.covariate_col
    if not cov:
        return est
    if spec.type == "ratio":
        diags.append(Diagnostic(
            name="cuped", severity="info", passed=True, assessed=False,
            message="CUPED is not implemented for ratio metrics; the raw estimate is reported."))
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


def period_index(dates: pd.Series, bin_days: int = 1) -> tuple[pd.Series, dict[int, str]]:
    """Days since the first date, binned; NaN where the date is missing or not ISO-8601.

    Numeric columns are read as a day count. Text must be ISO-8601 (``YYYY-MM-DD`` with an
    optional time): ambiguous formats such as ``03/04/2026`` are not guessed at.
    """
    nothing = pd.Series(np.nan, index=dates.index, dtype=np.float64)
    if pd.api.types.is_bool_dtype(dates):
        return nothing, {}
    epoch_day: float | None = None
    if pd.api.types.is_numeric_dtype(dates):
        values = dates.astype(np.float64)
        days = np.floor(values.where(np.isfinite(values)))
    else:
        try:
            parsed = pd.to_datetime(dates, errors="coerce", utc=True, format="ISO8601")
            seconds = parsed.dt.tz_localize(None).astype("datetime64[s]").astype(np.int64)
        except (ValueError, TypeError, OverflowError):  # objects that are not dates at all
            return nothing, {}
        # whole days since 1970-01-01 as plain numbers: no overflow for far-apart dates
        days = pd.Series(np.floor(seconds.to_numpy() / 86400.0), index=dates.index).where(
            parsed.notna())
    if days.notna().sum() == 0:
        return nothing, {}
    first = float(days.min())
    if not pd.api.types.is_numeric_dtype(dates):
        epoch_day = first
    idx = np.floor((days - first) / bin_days) * bin_days
    names: dict[int, str] = {}
    for value in sorted(idx.dropna().unique()):
        key = int(value)
        names[key] = (str(np.datetime64(int(epoch_day) + key, "D")) if epoch_day is not None
                      else f"day {key}")
    return idx, names


def _novelty(
    fr: _Frames, config: ExperimentConfig, date_col: str, repeated_units: bool
) -> NoveltyResult:
    """Per-period effects of the primary metric and their trend over time."""
    if repeated_units:
        return novelty.not_assessed(
            "rows are not one per randomised unit, so per-period estimates would not be "
            "independent. Aggregate to units first.", config.alpha)
    spec = config.primary
    both = pd.concat([fr.control, fr.treatment])
    idx, names = period_index(both[date_col], config.date_bin_days)
    n_missing = int(idx.isna().sum())
    if n_missing == len(both):
        return novelty.not_assessed(
            f"column '{date_col}' holds no usable dates (ISO-8601 text, datetimes or a "
            "numeric day count are accepted).", config.alpha, n_missing)
    c_idx, t_idx = idx.loc[fr.control.index], idx.loc[fr.treatment.index]
    counts = pd.DataFrame({"c": c_idx.value_counts(), "t": t_idx.value_counts()}).fillna(0)
    eligible = counts[(counts["c"] >= novelty.MIN_UNITS_PER_ARM)
                      & (counts["t"] >= novelty.MIN_UNITS_PER_ARM)].index
    excluded = len(counts) - len(eligible)
    if len(eligible) > novelty.MAX_PERIODS:
        return novelty.not_assessed(
            f"{len(eligible)} periods exceed the limit of {novelty.MAX_PERIODS}; use a larger "
            "date_bin_days.", config.alpha, n_missing, excluded)
    periods: list[PeriodEffect] = []
    for value in sorted(eligible):
        c, t = fr.control[c_idx == value], fr.treatment[t_idx == value]
        try:
            est = _estimate(c, t, spec, config.alpha)
        except ValueError:
            excluded += 1
            continue
        if est.std_error is None or not est.std_error > 0:
            excluded += 1
            continue
        periods.append(PeriodEffect(
            index=int(value), label=names[int(value)], n_control=est.n_control,
            n_treatment=est.n_treatment, effect=est.absolute_effect, std_error=est.std_error))
    return novelty.assess_novelty(periods, config.alpha, excluded_periods=excluded,
                                  rows_without_date=n_missing)


def novelty_analysis(df: pd.DataFrame, config: ExperimentConfig) -> NoveltyResult:
    """Novelty diagnostic alone (the same computation ``analyze_experiment`` runs)."""
    if not config.date_col:
        raise ValueError("novelty analysis needs config.date_col")
    report = analyze_experiment(df, config.model_copy(update={
        "segment_col": None, "aa_relabels": 0}))
    return cast(NoveltyResult, report.novelty)


def _segments(
    fr: _Frames, config: ExperimentConfig, col: str
) -> tuple[SegmentAnalysis | None, str | None]:
    """Exploratory per-segment effects of the primary metric."""
    spec = config.primary
    # Labels are compared as text so that mixed types (1, "1", 2.0) cannot break the grouping.
    seg_c, seg_t = (s.where(s.isna(), s.astype(str)) for s in (fr.control[col],
                                                               fr.treatment[col]))
    n_missing = int(seg_c.isna().sum() + seg_t.isna().sum())
    counts = pd.DataFrame({"c": seg_c.value_counts(), "t": seg_t.value_counts()}).fillna(0)
    if len(counts) < 2:
        return None, f"column '{col}' has fewer than 2 levels."
    if len(counts) > heterogeneity.MAX_SEGMENTS:
        return None, (f"column '{col}' has {len(counts)} levels; exploratory cuts are limited "
                      f"to {heterogeneity.MAX_SEGMENTS}. Use a coarser grouping.")
    skipped: list[SkippedSegment] = []
    ok: dict[str, tuple[pd.DataFrame, pd.DataFrame, EffectEstimate]] = {}
    for level in sorted(counts.index, key=str):
        n_c, n_t = int(counts.loc[level, "c"]), int(counts.loc[level, "t"])
        name = str(level)
        if min(n_c, n_t) < heterogeneity.MIN_UNITS_PER_ARM:
            skipped.append(SkippedSegment(
                segment=name, n_control=n_c, n_treatment=n_t,
                reason=f"fewer than {heterogeneity.MIN_UNITS_PER_ARM} units in an arm"))
            continue
        c, t = fr.control[seg_c == level], fr.treatment[seg_t == level]
        try:
            est = _estimate(c, t, spec, config.alpha)
        except ValueError as exc:
            skipped.append(SkippedSegment(segment=name, n_control=n_c, n_treatment=n_t,
                                          reason=str(exc)))
            continue
        if est.std_error is None or not est.std_error > 0:
            skipped.append(SkippedSegment(segment=name, n_control=n_c, n_treatment=n_t,
                                          reason="no variation in the metric"))
            continue
        ok[name] = (c, t, est)
    if not ok:
        return None, (f"no level of '{col}' has {heterogeneity.MIN_UNITS_PER_ARM}+ units per "
                      "arm with variation in the metric.")
    alpha_family = config.alpha / len(ok)
    return heterogeneity.summarise_segments(
        {n: e for n, (_, _, e) in ok.items()},
        {n: _estimate(c, t, spec, alpha_family) for n, (c, t, _) in ok.items()},
        col, config.alpha, config.segment_correction, skipped, n_missing), None


def segment_analysis(df: pd.DataFrame, config: ExperimentConfig) -> SegmentAnalysis | None:
    """Exploratory segment analysis alone (``None`` when it cannot be run)."""
    if not config.segment_col:
        raise ValueError("segment analysis needs config.segment_col")
    return analyze_experiment(df, config.model_copy(update={
        "date_col": None, "aa_relabels": 0})).segments


def _aa(fr: _Frames, config: ExperimentConfig) -> AAResult:
    spec = config.primary
    both = pd.concat([fr.control, fr.treatment])
    return aa_check(
        both, spec.column, spec.type, denominator=spec.denominator, unit_col=config.unit_col,
        treatment_share=len(fr.treatment) / len(both), n_relabels=config.aa_relabels,
        alpha=config.alpha, seed=config.seed)
