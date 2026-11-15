"""Novelty-effect diagnostic: does the treatment effect shrink with time since exposure began?

Input: one independent effect estimate per time period (for example per day of first
exposure), each with its standard error. The diagnostic fits a weighted straight line to the
effects (weights ``1 / SE^2``) and tests its slope. It is a warning with its evidence, never
proof: a shrinking effect is also produced by a changing mix of units over time, by
seasonality and by chance.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.stats import t as student_t

from ab_testing_copilot.models import Diagnostic, NoveltyResult, PeriodEffect

MIN_PERIODS = 5
MIN_UNITS_PER_ARM = 50
MAX_PERIODS = 400
# A fitted line that ends on the other side of zero still counts as fading when it overshoots
# by less than this share of its starting size; beyond that the effect has changed sign.
OVERSHOOT_RATIO = 0.5
CAVEAT = (
    "This is a warning, not proof: a changing mix of units over time, seasonality or chance "
    "produce the same pattern."
)


def effect_trend(
    index: Sequence[float], effects: Sequence[float], std_errors: Sequence[float]
) -> tuple[float, float, float, int, float, float]:
    """Weighted least-squares line through independent effect estimates.

    Returns ``(slope, slope_se, statistic, dof, p_value, weighted_mean)``. The slope standard
    error is never smaller than the one implied by the supplied standard errors: it is
    multiplied by ``sqrt(max(1, residual mean square))``, and the p-value uses a t distribution
    with ``n - 2`` degrees of freedom. Extra day-to-day variation therefore widens the test
    instead of producing false alarms.
    """
    x = np.asarray(index, dtype=np.float64)
    y = np.asarray(effects, dtype=np.float64)
    se = np.asarray(std_errors, dtype=np.float64)
    if not (x.size == y.size == se.size):
        raise ValueError("index, effects and std_errors must have the same length")
    if x.size < 3:
        raise ValueError("a trend needs at least 3 periods")
    if not (np.isfinite(x).all() and np.isfinite(y).all() and np.isfinite(se).all()):
        raise ValueError("index, effects and std_errors must be finite")
    if (se <= 0).any():
        raise ValueError("standard errors must be > 0")
    w = 1.0 / se**2
    x_bar = float((w * x).sum() / w.sum())
    y_bar = float((w * y).sum() / w.sum())
    sxx = float((w * (x - x_bar) ** 2).sum())
    if not sxx > 0:
        raise ValueError("all periods share the same index; a trend is undefined")
    slope = float((w * (x - x_bar) * (y - y_bar)).sum() / sxx)
    dof = int(x.size - 2)
    resid = y - (y_bar + slope * (x - x_bar))
    scale = max(1.0, float((w * resid**2).sum()) / dof)
    slope_se = math.sqrt(scale / sxx)
    stat = slope / slope_se
    p = float(2 * student_t.sf(abs(stat), dof))
    return slope, slope_se, stat, dof, p, y_bar


def _pooled(periods: Sequence[PeriodEffect]) -> tuple[float, float]:
    w = np.array([1.0 / p.std_error**2 for p in periods])
    e = np.array([p.effect for p in periods])
    return float((w * e).sum() / w.sum()), float(math.sqrt(1.0 / w.sum()))


def not_assessed(reason: str, alpha: float = 0.05, rows_without_date: int = 0,
                 excluded_periods: int = 0) -> NoveltyResult:
    return NoveltyResult(
        assessed=False, reason=reason, alpha=alpha, rows_without_date=rows_without_date,
        excluded_periods=excluded_periods,
        message=f"Novelty effect not assessed: {reason}",
    )


def assess_novelty(
    periods: Sequence[PeriodEffect], alpha: float = 0.05, min_periods: int = MIN_PERIODS,
    excluded_periods: int = 0, rows_without_date: int = 0,
) -> NoveltyResult:
    """Test whether per-period treatment effects move towards zero over time.

    ``periods`` must hold independent estimates (different units in each period). ``index`` is
    the time since the first exposure, in days. A significant trend is one of three things:
    *decay* (the fitted effect ends closer to zero on the same side, or overshoots zero by at
    most ``OVERSHOOT_RATIO`` of its starting size), which is the novelty warning; *growth*
    (same side, larger at the end); or a *reversal* (the sign changes). Only decay is a
    warning; the other two are reported for information.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    usable = sorted((p for p in periods if math.isfinite(p.std_error) and p.std_error > 0
                     and math.isfinite(p.effect)), key=lambda p: p.index)
    dropped = excluded_periods + (len(periods) - len(usable))
    if len(usable) < max(3, min_periods):
        return not_assessed(
            f"only {len(usable)} usable period(s); at least {max(3, min_periods)} are needed "
            f"(each with {MIN_UNITS_PER_ARM}+ units per arm and some variation).",
            alpha, rows_without_date, dropped)
    idx = [float(p.index) for p in usable]
    if len(set(idx)) < 3:
        return not_assessed("fewer than 3 distinct time points.", alpha, rows_without_date,
                            dropped)
    slope, slope_se, stat, dof, p_value, mean = effect_trend(
        idx, [p.effect for p in usable], [p.std_error for p in usable])
    w = np.array([1.0 / p.std_error**2 for p in usable])
    x_bar = float((w * np.array(idx)).sum() / w.sum())
    start, end = mean + slope * (idx[0] - x_bar), mean + slope * (idx[-1] - x_bar)
    half = len(usable) // 2
    early, early_se = _pooled(usable[:half])
    late, late_se = _pooled(usable[len(usable) - half:])
    significant = p_value < alpha
    same_side = start * end >= 0
    decay = significant and (abs(end) < abs(start) if same_side
                             else abs(end) <= OVERSHOOT_RATIO * abs(start))
    reversal = significant and not same_side and not decay
    growth = significant and same_side and not decay
    evidence = (
        f"slope {slope:+.4g} per day (SE {slope_se:.3g}, t = {stat:.2f} on {dof} df, "
        f"p = {p_value:.3g}) over {len(usable)} periods; fitted effect {start:+.4g} at the "
        f"start and {end:+.4g} at the end; first-half effect {early:+.4g} (SE {early_se:.3g}) "
        f"vs second-half {late:+.4g} (SE {late_se:.3g})."
    )
    if decay:
        msg = ("Possible novelty effect: the treatment effect shrinks towards zero over time, "
               f"so the pooled estimate may overstate the lasting effect. Evidence: {evidence} "
               f"{CAVEAT} Consider running longer or re-testing on a later cohort.")
    elif growth:
        msg = ("The treatment effect grows in size over time, so the pooled estimate may "
               f"understate the lasting effect. Evidence: {evidence} {CAVEAT}")
    elif reversal:
        msg = ("The treatment effect changes sign over time, so the pooled estimate averages "
               f"opposite effects. Evidence: {evidence} {CAVEAT}")
    else:
        msg = (f"No clear time trend in the treatment effect: {evidence} The check has limited "
               "power, so this does not rule out a novelty effect.")
    if dropped:
        msg += f" {dropped} period(s) were left out (too few units or no variation)."
    if rows_without_date:
        msg += f" {rows_without_date} row(s) without a usable date were left out of this check."
    return NoveltyResult(
        assessed=True, alpha=alpha, periods=list(usable), excluded_periods=dropped,
        rows_without_date=rows_without_date, slope=slope, slope_std_error=slope_se,
        statistic=stat, dof=dof, p_value=p_value, fitted_start=start, fitted_end=end,
        early_effect=early, early_std_error=early_se, late_effect=late, late_std_error=late_se,
        decay_detected=decay, growth_detected=growth, reversal_detected=reversal, message=msg,
    )


def novelty_diagnostic(result: NoveltyResult) -> Diagnostic:
    """Decay is a failed warning (weakens the evidence rating); it never blocks a decision."""
    if not result.assessed:
        return Diagnostic(name="novelty_effect", severity="info", passed=True, assessed=False,
                          message=result.message)
    return Diagnostic(
        name="novelty_effect", severity="warning" if result.decay_detected else "info",
        passed=not result.decay_detected, message=result.message, p_value=result.p_value)
