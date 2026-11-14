"""Heterogeneous treatment effects across segments. Exploratory by construction.

Per-segment effects get multiplicity-adjusted p-values and simultaneous intervals, and
Cochran's Q tests whether the absolute effect is the same in every segment. Nothing in this
module feeds the ship / no-ship decision: segment findings are hypotheses for a new,
pre-registered experiment.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np
from scipy.stats import chi2

from ab_testing_copilot.analysis import adjust_pvalues
from ab_testing_copilot.models import (
    Correction,
    Diagnostic,
    EffectEstimate,
    SegmentAnalysis,
    SegmentEffect,
    SkippedSegment,
)

MIN_UNITS_PER_ARM = 30
MAX_SEGMENTS = 30


def cochran_q(
    effects: Sequence[float], std_errors: Sequence[float]
) -> tuple[float, int, float, float, float]:
    """Cochran's Q test of equal effects: ``(Q, dof, p_value, I^2, pooled_effect)``.

    The pooled effect is the inverse-variance weighted mean. Under equal true effects and
    independent, approximately normal estimates, Q follows a chi-square with ``k - 1`` degrees
    of freedom. I^2 = max(0, (Q - dof) / Q) is the share of variation beyond sampling error.
    """
    e = np.asarray(effects, dtype=np.float64)
    se = np.asarray(std_errors, dtype=np.float64)
    if e.size != se.size:
        raise ValueError("effects and std_errors must have the same length")
    if e.size < 2:
        raise ValueError("a heterogeneity test needs at least 2 segments")
    if not (np.isfinite(e).all() and np.isfinite(se).all()) or (se <= 0).any():
        raise ValueError("effects must be finite and standard errors finite and > 0")
    w = 1.0 / se**2
    pooled = float((w * e).sum() / w.sum())
    q = float((w * (e - pooled) ** 2).sum())
    dof = int(e.size - 1)
    i2 = max(0.0, (q - dof) / q) if q > 0 else 0.0
    return q, dof, float(chi2.sf(q, dof)), i2, pooled


def summarise_segments(
    estimates: Mapping[str, EffectEstimate], simultaneous: Mapping[str, EffectEstimate],
    segment_col: str, alpha: float, correction: Correction = "holm",
    skipped: Sequence[SkippedSegment] = (), units_without_segment: int = 0,
) -> SegmentAnalysis:
    """Combine per-segment estimates into an exploratory report.

    ``estimates`` are computed at ``alpha``; ``simultaneous`` holds the same segments at
    ``alpha / m`` (Bonferroni), giving intervals that cover all segments at once.
    """
    names = list(estimates)
    if set(names) != set(simultaneous):
        raise ValueError("estimates and simultaneous must cover the same segments")
    adjusted = adjust_pvalues([estimates[n].p_value for n in names], correction)
    segments = [
        SegmentEffect(
            segment=n, estimate=estimates[n], adjusted_p_value=adj,
            significant_after_correction=adj < alpha,
            simultaneous_ci_low=simultaneous[n].ci_low,
            simultaneous_ci_high=simultaneous[n].ci_high,
        )
        for n, adj in zip(names, adjusted, strict=True)
    ]
    kind = "false discovery rate" if correction == "benjamini-hochberg" else "family-wise error"
    parts = [f"{len(segments)} segment(s) of '{segment_col}' analysed"]
    if skipped:
        parts.append(f"{len(skipped)} left out (fewer than {MIN_UNITS_PER_ARM} units per arm "
                     "or no variation)")
    if units_without_segment:
        parts.append(f"{units_without_segment} unit(s) without a segment value left out")
    msg = "Exploratory segment analysis: " + "; ".join(parts) + ". "
    q = dof = p = i2 = pooled = None
    detected = False
    usable = [s for s in segments if s.estimate.std_error and s.estimate.std_error > 0
              and math.isfinite(s.estimate.std_error)]
    if len(usable) >= 2:
        q, dof, p, i2, pooled = cochran_q(
            [s.estimate.absolute_effect for s in usable],
            [float(s.estimate.std_error or 0.0) for s in usable])
        detected = p < alpha
        msg += (f"Cochran's Q = {q:.2f} on {dof} df, p = {p:.3g}, I^2 = {i2:.0%}: "
                + ("the absolute effect appears to differ between segments. "
                   if detected else "no clear evidence that the absolute effect differs. "))
    else:
        msg += "Too few usable segments for a heterogeneity test. "
    n_sig = sum(s.significant_after_correction for s in segments)
    msg += (f"{n_sig} segment(s) significant after {correction} correction ({kind} "
            f"{alpha:.3g}). These are hypotheses for a follow-up experiment, not findings; "
            "they do not change the recommendation.")
    return SegmentAnalysis(
        segment_col=segment_col, correction=correction, alpha=alpha, segments=segments,
        skipped=list(skipped), units_without_segment=units_without_segment,
        pooled_effect=pooled, q_statistic=q, q_dof=dof, q_p_value=p, i_squared=i2,
        heterogeneity_detected=detected, message=msg,
    )


def segment_diagnostic(result: SegmentAnalysis | None, reason: str | None = None) -> Diagnostic:
    """Always informational and always 'passed': exploratory results never touch the decision."""
    if result is None:
        return Diagnostic(name="segments_exploratory", severity="info", passed=True,
                          assessed=False,
                          message=f"Exploratory segment analysis not run: {reason}")
    return Diagnostic(name="segments_exploratory", severity="info", passed=True,
                      message=result.message, p_value=result.q_p_value)
