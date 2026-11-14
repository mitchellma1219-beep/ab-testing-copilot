"""Experiment validity diagnostics."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
from scipy.stats import chisquare

from ab_testing_copilot.analysis import two_proportion_core
from ab_testing_copilot.models import Diagnostic

SRM_ALPHA = 0.001


def srm_check(
    n_control: int, n_treatment: int, expected_treatment_share: float = 0.5,
    threshold: float = SRM_ALPHA,
) -> Diagnostic:
    """Sample Ratio Mismatch: chi-square goodness of fit against the planned allocation."""
    if n_control < 0 or n_treatment < 0 or n_control + n_treatment == 0:
        raise ValueError("arm counts must be non-negative and not both zero")
    if not 0 < expected_treatment_share < 1:
        raise ValueError("expected_treatment_share must be in (0, 1)")
    total = n_control + n_treatment
    exp = [total * (1 - expected_treatment_share), total * expected_treatment_share]
    p = float(chisquare([n_control, n_treatment], f_exp=exp).pvalue)
    ok = p >= threshold
    share = n_treatment / total
    msg = (
        f"Observed treatment share {share:.4f} vs planned {expected_treatment_share:.4f} "
        f"(chi-square p = {p:.3g}). "
        + ("No evidence of SRM." if ok else
           "Sample ratio mismatch: assignment or logging is likely broken; "
           "effect estimates cannot be trusted until the cause is found.")
    )
    return Diagnostic(name="sample_ratio_mismatch", severity="info" if ok else "blocking",
                      passed=ok, message=msg, p_value=p)


def missing_data_check(
    missing_control: int, n_control: int, missing_treatment: int, n_treatment: int
) -> Diagnostic:
    """Differential missingness between arms (two-proportion z test on missing rates)."""
    if n_control < 1 or n_treatment < 1:
        raise ValueError("both arms need at least one row")
    rc, rt = missing_control / n_control, missing_treatment / n_treatment
    if missing_control + missing_treatment == 0:
        return Diagnostic(name="missing_data", severity="info", passed=True,
                          message="No missing metric values.")
    *_, p_arr = two_proportion_core(missing_control, n_control, missing_treatment, n_treatment)
    p = float(p_arr)
    differential = p < 0.01
    msg = f"Missing metric rate: control {rc:.2%}, treatment {rt:.2%} (p = {p:.3g}). "
    if differential:
        msg += ("Missingness differs by arm, so dropping rows can bias the estimate; "
                "investigate the logging pipeline.")
        return Diagnostic(name="missing_data", severity="blocking", passed=False,
                          message=msg, p_value=p)
    msg += "Rows with missing values were dropped (assumes missing completely at random)."
    # Non-differential loss below 5% is noted; above that it weakens the evidence rating.
    minor = max(rc, rt) < 0.05
    return Diagnostic(name="missing_data", severity="warning", passed=minor, message=msg,
                      p_value=p)


def outlier_check(values: Sequence[float] | npt.NDArray[np.generic], arm: str) -> Diagnostic:
    """Flag heavy tails where a handful of units dominate the arm total."""
    a = np.asarray(values, dtype=np.float64)
    if a.size < 20:
        return Diagnostic(name=f"outliers_{arm}", severity="info", passed=True,
                          message=f"{arm}: too few rows for an outlier screen.")
    med = float(np.median(a))
    mad = float(np.median(np.abs(a - med))) * 1.4826
    spread = mad if mad > 0 else float(a.std(ddof=1))
    extreme = int((np.abs(a - med) > 10 * spread).sum()) if spread > 0 else 0
    top = np.sort(np.abs(a))[-max(1, a.size // 100):].sum()
    total = float(np.abs(a).sum())
    share = float(top / total) if total > 0 else 0.0
    flagged = extreme > 0 and share > 0.3
    msg = (f"{arm}: {extreme} value(s) beyond 10 robust SDs; top 1% of units hold "
           f"{share:.0%} of the total. ")
    msg += ("The mean is dominated by a few units; compare with the bootstrap interval "
            "and consider a pre-registered winsorisation." if flagged else "No dominant outliers.")
    return Diagnostic(name=f"outliers_{arm}", severity="warning" if flagged else "info",
                      passed=not flagged, message=msg)


def covariate_balance_check(
    x_control: Sequence[float] | npt.NDArray[np.generic],
    x_treatment: Sequence[float] | npt.NDArray[np.generic],
    n_sigma: float = 4.0,
) -> Diagnostic:
    """Randomisation check: standardised mean difference of a pre-experiment covariate."""
    c, t = np.asarray(x_control, dtype=np.float64), np.asarray(x_treatment, dtype=np.float64)
    pooled = float(np.sqrt((c.var(ddof=1) + t.var(ddof=1)) / 2))
    smd = float((t.mean() - c.mean()) / pooled) if pooled > 0 else 0.0
    # Under valid randomisation SMD ~ N(0, 1/n_c + 1/n_t); flag beyond ``n_sigma`` of that
    # (false-alarm probability about 6e-5 at the default of 4).
    limit = n_sigma * float(np.sqrt(1 / c.size + 1 / t.size))
    ok = abs(smd) <= limit
    msg = f"Pre-experiment covariate standardised mean difference = {smd:+.4f} "
    msg += f"(limit {limit:.4f}). "
    msg += ("Arms look balanced." if ok
            else "Arms differ before treatment: randomisation is suspect.")
    return Diagnostic(name="covariate_balance", severity="info" if ok else "blocking",
                      passed=ok, message=msg)


def peeking_check(n_looks: int, alpha: float) -> Diagnostic:
    """Warn about repeated significance testing; the caller applies alpha / n_looks."""
    if n_looks < 1:
        raise ValueError("n_looks must be >= 1")
    if n_looks == 1:
        return Diagnostic(name="peeking", severity="info", passed=True,
                          message="Single planned analysis (fixed horizon).")
    return Diagnostic(
        name="peeking", severity="warning", passed=False,
        message=(f"Results were inspected {n_looks} times. Unadjusted repeated testing inflates "
                 f"the false-positive rate above {alpha:.3g}; a conservative Bonferroni threshold "
                 f"of {alpha / n_looks:.4g} per look is applied to the primary metric."),
    )
