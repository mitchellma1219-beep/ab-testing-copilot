"""Effect estimation: proportions, means, bootstrap, CUPED and multiplicity corrections.

The ``*_core`` functions are vectorised over NumPy arrays so the Monte Carlo engine
exercises exactly the same arithmetic as the scalar public API.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
import numpy.typing as npt
from scipy.stats import norm
from scipy.stats import t as student_t

from ab_testing_copilot.models import EffectEstimate

FloatArray = npt.NDArray[np.float64]
Correction = Literal["bonferroni", "holm", "benjamini-hochberg"]


def _arr(x: object) -> FloatArray:
    return np.asarray(x, dtype=np.float64)


def two_proportion_core(
    x_c: object, n_c: object, x_t: object, n_t: object, alpha: float = 0.05
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
    """Return (diff, ci_low, ci_high, z, p). Pooled-SE z test, unpooled Wald interval."""
    xc, nc, xt, nt = _arr(x_c), _arr(n_c), _arr(x_t), _arr(n_t)
    pc, pt = xc / nc, xt / nt
    diff = pt - pc
    pool = (xc + xt) / (nc + nt)
    se0 = np.sqrt(pool * (1 - pool) * (1 / nc + 1 / nt))
    se1 = np.sqrt(pc * (1 - pc) / nc + pt * (1 - pt) / nt)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(se0 > 0, diff / se0, 0.0)
    p = 2 * norm.sf(np.abs(z))
    crit = norm.ppf(1 - alpha / 2)
    return diff, diff - crit * se1, diff + crit * se1, z, _arr(p)


def welch_core(
    m_c: object, v_c: object, n_c: object, m_t: object, v_t: object, n_t: object,
    alpha: float = 0.05,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
    """Return (diff, ci_low, ci_high, t, p) for Welch's unequal-variance t test."""
    mc, vc, nc, mt, vt, nt = (_arr(a) for a in (m_c, v_c, n_c, m_t, v_t, n_t))
    diff = mt - mc
    a, b = vc / nc, vt / nt
    se = np.sqrt(a + b)
    with np.errstate(divide="ignore", invalid="ignore"):
        df = np.where(se > 0, (a + b) ** 2 / (a**2 / (nc - 1) + b**2 / (nt - 1)), 1.0)
        tstat = np.where(se > 0, diff / se, np.where(diff == 0, 0.0, np.sign(diff) * np.inf))
    p = _arr(2 * student_t.sf(np.abs(tstat), df))
    crit = student_t.ppf(1 - alpha / 2, df)
    return diff, diff - crit * se, diff + crit * se, tstat, p


def _relative(
    c: float, t: float, var_c: float, var_t: float, alpha: float
) -> tuple[float | None, float | None, float | None]:
    """Relative lift t/c - 1 with a delta-method interval; undefined if control <= 0."""
    if not c > 0:
        return None, None, None
    rel = t / c - 1
    se = float(np.sqrt(var_t / c**2 + t**2 * var_c / c**4))
    crit = float(norm.ppf(1 - alpha / 2))
    return rel, rel - crit * se, rel + crit * se


def compare_proportions(
    conversions_control: int,
    n_control: int,
    conversions_treatment: int,
    n_treatment: int,
    alpha: float = 0.05,
    metric: str = "conversion_rate",
) -> EffectEstimate:
    """Two-sided comparison of two conversion rates."""
    for name, x, n in (
        ("control", conversions_control, n_control),
        ("treatment", conversions_treatment, n_treatment),
    ):
        if n < 1:
            raise ValueError(f"{name} arm is empty")
        if not 0 <= x <= n:
            raise ValueError(f"{name} conversions must be within [0, n]; got {x} of {n}")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    diff, lo, hi, z, p = two_proportion_core(
        conversions_control, n_control, conversions_treatment, n_treatment, alpha
    )
    pc, pt = conversions_control / n_control, conversions_treatment / n_treatment
    warnings: list[str] = []
    cells = (
        conversions_control, n_control - conversions_control,
        conversions_treatment, n_treatment - conversions_treatment,
    )
    if min(cells) < 5:
        warnings.append(
            "A cell count is below 5: the normal approximation is unreliable; "
            "prefer an exact test or collect more data."
        )
    if pc in (0.0, 1.0) and pt in (0.0, 1.0):
        warnings.append("Both arms have zero variance; the Wald interval is degenerate.")
    rel, rlo, rhi = _relative(pc, pt, pc * (1 - pc) / n_control, pt * (1 - pt) / n_treatment, alpha)
    return EffectEstimate(
        metric=metric, metric_type="binary",
        method="two-proportion z test (pooled SE); Wald CI (unpooled SE); delta-method relative CI",
        n_control=n_control, n_treatment=n_treatment,
        control_value=pc, treatment_value=pt,
        absolute_effect=float(diff), ci_low=float(lo), ci_high=float(hi),
        relative_effect=rel, rel_ci_low=rlo, rel_ci_high=rhi,
        statistic=float(z), p_value=float(p), alpha=alpha, warnings=warnings,
    )


def _clean(values: Sequence[float] | npt.NDArray[np.generic], name: str) -> FloatArray:
    a = np.asarray(values, dtype=np.float64).ravel()
    if np.isnan(a).any() or np.isinf(a).any():
        raise ValueError(f"{name} contains NaN or infinite values; clean or drop them explicitly")
    if a.size < 2:
        raise ValueError(f"{name} needs at least 2 observations, got {a.size}")
    return a


def compare_means(
    control: Sequence[float] | npt.NDArray[np.generic],
    treatment: Sequence[float] | npt.NDArray[np.generic],
    alpha: float = 0.05,
    metric: str = "metric",
) -> EffectEstimate:
    """Welch's t test on two samples of a continuous metric."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    c, t = _clean(control, "control"), _clean(treatment, "treatment")
    mc, mt = float(c.mean()), float(t.mean())
    vc, vt = float(c.var(ddof=1)), float(t.var(ddof=1))
    diff, lo, hi, stat, p = welch_core(mc, vc, c.size, mt, vt, t.size, alpha)
    warnings: list[str] = []
    if vc == 0 and vt == 0:
        warnings.append("Both arms have zero variance; the t test is not meaningful.")
    if min(c.size, t.size) < 30:
        warnings.append("Fewer than 30 observations in an arm: t-test relies on near-normal data.")
    rel, rlo, rhi = _relative(mc, mt, vc / c.size, vt / t.size, alpha)
    return EffectEstimate(
        metric=metric, metric_type="continuous",
        method="Welch t test; delta-method relative CI",
        n_control=int(c.size), n_treatment=int(t.size),
        control_value=mc, treatment_value=mt,
        absolute_effect=float(diff), ci_low=float(lo), ci_high=float(hi),
        relative_effect=rel, rel_ci_low=rlo, rel_ci_high=rhi,
        statistic=float(stat), p_value=float(p), alpha=alpha, warnings=warnings,
    )


def bootstrap_mean_diff(
    control: Sequence[float] | npt.NDArray[np.generic],
    treatment: Sequence[float] | npt.NDArray[np.generic],
    alpha: float = 0.05,
    n_boot: int = 5000,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Percentile bootstrap CI for mean(treatment) - mean(control): (estimate, low, high)."""
    if n_boot < 100:
        raise ValueError("n_boot must be >= 100")
    c, t = _clean(control, "control"), _clean(treatment, "treatment")
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot)
    chunk = max(1, min(n_boot, 4_000_000 // max(c.size, t.size)))
    for start in range(0, n_boot, chunk):
        k = min(chunk, n_boot - start)
        cm = c[rng.integers(0, c.size, size=(k, c.size))].mean(axis=1)
        tm = t[rng.integers(0, t.size, size=(k, t.size))].mean(axis=1)
        diffs[start : start + k] = tm - cm
    lo, hi = np.quantile(diffs, [alpha / 2, 1 - alpha / 2])
    return float(t.mean() - c.mean()), float(lo), float(hi)


def cuped_adjust(
    y_control: Sequence[float] | npt.NDArray[np.generic],
    x_control: Sequence[float] | npt.NDArray[np.generic],
    y_treatment: Sequence[float] | npt.NDArray[np.generic],
    x_treatment: Sequence[float] | npt.NDArray[np.generic],
) -> tuple[FloatArray, FloatArray, float, float]:
    """CUPED: y_adj = y - theta * (x - mean(x)) with theta pooled across arms.

    ``x`` must be a pre-experiment covariate (unaffected by treatment). Returns
    (y_control_adj, y_treatment_adj, theta, variance_reduction) where variance reduction is
    1 - var(adjusted) / var(raw) on the pooled, arm-centred data.
    """
    yc, xc = _clean(y_control, "y_control"), _clean(x_control, "x_control")
    yt, xt = _clean(y_treatment, "y_treatment"), _clean(x_treatment, "x_treatment")
    if yc.size != xc.size or yt.size != xt.size:
        raise ValueError("metric and covariate must have the same length within each arm")
    # Centre within arm so the treatment effect does not contaminate theta.
    yy = np.concatenate([yc - yc.mean(), yt - yt.mean()])
    xx = np.concatenate([xc - xc.mean(), xt - xt.mean()])
    var_x = float(xx @ xx)
    if var_x == 0:
        return yc, yt, 0.0, 0.0
    theta = float(xx @ yy) / var_x
    grand = float(np.concatenate([xc, xt]).mean())
    yc_adj, yt_adj = yc - theta * (xc - grand), yt - theta * (xt - grand)
    raw = float(yy @ yy)
    resid = yy - theta * xx
    reduction = 1 - float(resid @ resid) / raw if raw > 0 else 0.0
    return yc_adj, yt_adj, theta, reduction


def adjust_pvalues(p_values: Sequence[float], method: Correction = "holm") -> list[float]:
    """Adjusted p-values. Bonferroni/Holm control FWER; Benjamini-Hochberg controls FDR."""
    p = np.asarray(p_values, dtype=np.float64)
    if p.size == 0:
        return []
    if np.isnan(p).any() or (p < 0).any() or (p > 1).any():
        raise ValueError("p-values must be within [0, 1]")
    m = p.size
    order = np.argsort(p)
    ranked = p[order]
    if method == "bonferroni":
        adj = np.minimum(ranked * m, 1.0)
    elif method == "holm":
        adj = np.minimum(np.maximum.accumulate(ranked * (m - np.arange(m))), 1.0)
    elif method == "benjamini-hochberg":
        adj = np.minimum(np.minimum.accumulate((ranked * m / np.arange(1, m + 1))[::-1])[::-1], 1.0)
    else:
        raise ValueError(f"unknown correction method: {method}")
    out = np.empty(m)
    out[order] = adj
    return [float(v) for v in out]
