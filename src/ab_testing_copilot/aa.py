"""A/A check on the user's own data: re-label units at random and count false positives.

The labels are shuffled many times, the analysis is repeated on every shuffle, and the share
of shuffles that come out "significant" is compared with ``alpha``. Because the labels are
random, every rejection is a false positive. A rate well above ``alpha`` means the analysis
understates its uncertainty on this data, most often because rows are finer than the unit that
was randomised (sessions analysed as if they were users).
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import beta, binomtest

from ab_testing_copilot.analysis import FloatArray, ratio_core, two_proportion_core, welch_core
from ab_testing_copilot.models import AAResult, Diagnostic, MetricType

MIN_RELABELS, MAX_RELABELS = 100, 20_000
VERDICT_LEVEL = 0.01  # two-sided binomial test of the empirical rate against alpha
_MAX_CELLS = 4_000_000


def _unit_sums(df: pd.DataFrame, columns: list[str], unit_col: str | None) -> pd.DataFrame:
    """Per-unit row count and sums of the given columns (one row per unit)."""
    data = df[columns].astype(np.float64)
    if unit_col is None:
        out = data.copy()
        out.insert(0, "_rows", 1.0)
        return out.reset_index(drop=True)
    grouped = data.groupby(df[unit_col].to_numpy(), sort=False)
    out = grouped.sum()
    out.insert(0, "_rows", grouped.size().astype(np.float64))
    return out.reset_index(drop=True)


def aa_check(
    df: pd.DataFrame, metric: str, metric_type: MetricType, *, denominator: str | None = None,
    unit_col: str | None = None, treatment_share: float = 0.5, n_relabels: int = 1000,
    alpha: float = 0.05, seed: int = 0,
) -> AAResult:
    """Empirical false-positive rate of the test under random re-labelling.

    Labels are drawn per ``unit_col`` (per row if it is ``None``), with ``treatment_share`` of
    the units labelled treatment. The test is the one the pipeline applies to the table as
    given: a two-proportion z test (binary) or Welch's t test (continuous) on the *rows*, or
    the delta method on unit-level sums (ratio). Rows with a missing value are left out.
    The existing variant labels are not used, so the check also works on pre-experiment data.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    if not 0 < treatment_share < 1:
        raise ValueError("treatment_share must be in (0, 1)")
    if not MIN_RELABELS <= n_relabels <= MAX_RELABELS:
        raise ValueError(f"n_relabels must be between {MIN_RELABELS} and {MAX_RELABELS}")
    if metric_type == "ratio":
        if not denominator:
            raise ValueError("a ratio metric needs a denominator column")
    elif denominator:
        raise ValueError("denominator is only meaningful for a ratio metric")
    columns = [metric, denominator] if denominator else [metric]
    needed = columns + ([unit_col] if unit_col else [])
    missing = sorted(set(needed) - set(df.columns))
    if missing:
        raise ValueError(f"missing required column(s): {missing}; found {list(df.columns)}")
    for col in columns:
        if not pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]):
            raise ValueError(f"column '{col}' must be numeric, got dtype {df[col].dtype}")
    keep = df[columns].notna().all(axis=1)
    if unit_col:
        keep &= df[unit_col].notna()
    data = df.loc[keep]
    values = data[columns].to_numpy(np.float64)
    if not np.isfinite(values).all():
        raise ValueError(f"metric '{metric}' contains infinite values")
    if metric_type == "binary" and not np.isin(values, (0.0, 1.0)).all():
        raise ValueError(f"binary metric '{metric}' has values other than 0/1")
    if metric_type == "ratio" and (values[:, 1] < 0).any():
        raise ValueError("denominator values must be >= 0")

    # Second moments are taken around the overall mean to avoid cancellation in the variances.
    work = pd.DataFrame({"y": values[:, 0]})
    centre_y = float(values[:, 0].mean()) if len(values) else 0.0
    work["yc2"] = (work["y"] - centre_y) ** 2
    work["yc"] = work["y"] - centre_y
    if metric_type == "ratio":
        centre_d = float(values[:, 1].mean())
        work["d"] = values[:, 1]
        work["dc"] = work["d"] - centre_d
        work["dc2"] = work["dc"] ** 2
    if unit_col:
        work[unit_col] = data[unit_col].to_numpy()
    sums = _unit_sums(work, [c for c in work.columns if c != unit_col], unit_col)
    n_units = len(sums)
    n_treat = round(treatment_share * n_units)
    if n_units < 8 or min(n_treat, n_units - n_treat) < 4:
        raise ValueError(
            f"an A/A check needs at least 4 units per arm; got {n_units} unit(s) at a "
            f"treatment share of {treatment_share:.3g}")
    if metric_type == "ratio":
        # the delta method works on unit-level sums: one (x, d) pair per unit
        ux, ud = sums["y"].to_numpy(), sums["d"].to_numpy()
        if not ud.sum() > 0:
            raise ValueError("the denominator sums to zero; the ratio is undefined")
        cx, cd = ux - ux.mean(), ud - ud.mean()
        stats = np.column_stack([np.ones(n_units), ux, ud, cx, cd, cx * cx, cd * cd, cx * cd])
    else:
        stats = np.column_stack([sums["_rows"].to_numpy(), sums["y"].to_numpy(),
                                 sums["yc"].to_numpy(), sums["yc2"].to_numpy()])
    total = stats.sum(axis=0)

    rng = np.random.default_rng(seed)
    base = np.zeros(n_units, dtype=bool)
    base[:n_treat] = True
    p_values = np.empty(n_relabels)
    chunk = max(1, _MAX_CELLS // n_units)
    for start in range(0, n_relabels, chunk):
        k = min(chunk, n_relabels - start)
        labels = rng.permuted(np.broadcast_to(base, (k, n_units)), axis=1)
        treat = labels.astype(np.float64) @ stats
        ctrl = total[None, :] - treat
        p_values[start : start + k] = _p_values(metric_type, ctrl, treat, alpha)

    hits = int((p_values < alpha).sum())
    rate = hits / n_relabels
    se = math.sqrt(alpha * (1 - alpha) / n_relabels)
    lo = float(beta.ppf(0.025, hits, n_relabels - hits + 1)) if hits else 0.0
    hi = float(beta.ppf(0.975, hits + 1, n_relabels - hits)) if hits < n_relabels else 1.0
    p_binom = float(binomtest(hits, n_relabels, alpha).pvalue)
    verdict: Literal["calibrated", "inflated", "conservative"] = "calibrated"
    if p_binom < VERDICT_LEVEL:
        verdict = "inflated" if rate > alpha else "conservative"
    analysis = {
        "binary": "two-proportion z test on rows",
        "continuous": "Welch t test on rows",
        "ratio": "delta-method z test on unit-level sums",
    }[metric_type]
    unit = f"'{unit_col}'" if unit_col else "row"
    msg = (f"A/A check: {n_relabels} random re-labellings of {n_units:,} {unit} unit(s), "
           f"{analysis}: {rate:.1%} came out significant at alpha = {alpha:.3g} "
           f"(95% interval {lo:.1%} to {hi:.1%}, binomial p = {p_binom:.3g}). ")
    if verdict == "inflated":
        msg += ("The analysis rejects far more often than alpha when there is no effect, so its "
                "p-values and intervals are too optimistic on this data. Check the unit of "
                "analysis (aggregate to the randomised unit or use a ratio metric).")
    elif verdict == "conservative":
        msg += ("The analysis rejects less often than alpha on this data (for example heavy "
                "tails or very rare events): intervals are wider than needed and power is "
                "lower than designed.")
    else:
        msg += "The false-positive rate is consistent with alpha."
    return AAResult(
        analysis=analysis, relabelled_unit=unit_col or "row", n_units=n_units, n_rows=len(data),
        treatment_share=n_treat / n_units, n_relabels=n_relabels, seed=seed, alpha=alpha,
        false_positive_rate=rate, mc_standard_error=se, ci_low=lo, ci_high=hi,
        binomial_p_value=p_binom, verdict=verdict,
        p_value_histogram=[int(v) for v in np.histogram(p_values, bins=10, range=(0, 1))[0]],
        message=msg,
    )


def _p_values(metric_type: MetricType, c: FloatArray, t: FloatArray, alpha: float) -> FloatArray:
    """P-values for arrays of per-arm sufficient statistics (one row per re-labelling)."""
    if metric_type == "ratio":
        def moments(
            a: FloatArray,
        ) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
            n, sx, sd, scx, scd, sxx, sdd, sxd = (a[:, i] for i in range(8))
            mcx, mcd = scx / n, scd / n
            return (n, sx / n, sd / n, (sxx - n * mcx**2) / (n - 1), (sdd - n * mcd**2) / (n - 1),
                    (sxd - n * mcx * mcd) / (n - 1))

        return ratio_core(*moments(c), *moments(t), alpha=alpha)[4]
    n_c, n_t = c[:, 0], t[:, 0]
    if metric_type == "binary":
        return two_proportion_core(c[:, 1], n_c, t[:, 1], n_t, alpha)[4]
    with np.errstate(divide="ignore", invalid="ignore"):
        m_c, m_t = c[:, 2] / n_c, t[:, 2] / n_t  # means of the centred values
        v_c = np.maximum(c[:, 3] - n_c * m_c**2, 0.0) / (n_c - 1)
        v_t = np.maximum(t[:, 3] - n_t * m_t**2, 0.0) / (n_t - 1)
    return welch_core(m_c, v_c, n_c, m_t, v_t, n_t, alpha)[4]


def aa_diagnostic(result: AAResult) -> Diagnostic:
    """An inflated false-positive rate invalidates the analysis; the other verdicts inform."""
    bad = result.verdict == "inflated"
    return Diagnostic(name="aa_check", severity="blocking" if bad else "info", passed=not bad,
                      message=result.message, p_value=result.binomial_p_value)
