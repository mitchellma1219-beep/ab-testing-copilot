"""Experiment design: sample size, power, MDE and duration (normal-approximation formulas)."""

from __future__ import annotations

import math

from scipy.stats import norm

from ab_testing_copilot.models import SampleSizeResult


def _check_alpha_power(alpha: float, power: float) -> None:
    if not 0 < alpha < 1:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if not 0 < power < 1:
        raise ValueError(f"power must be in (0, 1), got {power}")


def _check_ratio(ratio: float) -> None:
    if not ratio > 0 or not math.isfinite(ratio):
        raise ValueError(f"allocation_ratio (n_treatment / n_control) must be > 0, got {ratio}")


def sample_size_for_proportions(
    baseline: float,
    absolute_mde: float,
    alpha: float = 0.05,
    power: float = 0.8,
    allocation_ratio: float = 1.0,
) -> SampleSizeResult:
    """Two-sided two-proportion z-test sample size (pooled null / unpooled alternative variance).

    ``allocation_ratio`` is n_treatment / n_control.
    """
    _check_alpha_power(alpha, power)
    _check_ratio(allocation_ratio)
    if not 0 < baseline < 1:
        raise ValueError(f"baseline must be in (0, 1), got {baseline}")
    p2 = baseline + absolute_mde
    if absolute_mde == 0 or not 0 < p2 < 1:
        raise ValueError("absolute_mde must be non-zero and keep baseline + mde inside (0, 1)")
    r = allocation_ratio
    z_a = float(norm.ppf(1 - alpha / 2))
    z_b = float(norm.ppf(power))
    p_bar = (baseline + r * p2) / (1 + r)
    num = (
        z_a * math.sqrt(p_bar * (1 - p_bar) * (1 + 1 / r))
        + z_b * math.sqrt(baseline * (1 - baseline) + p2 * (1 - p2) / r)
    ) ** 2
    n_c = math.ceil(num / absolute_mde**2)
    n_t = math.ceil(n_c * r)
    return SampleSizeResult(
        metric_type="binary",
        n_control=n_c,
        n_treatment=n_t,
        n_total=n_c + n_t,
        alpha=alpha,
        power=power,
        absolute_mde=absolute_mde,
        relative_mde=absolute_mde / baseline,
        allocation_ratio=r,
        assumptions=[
            "Two-sided test, normal approximation to the binomial.",
            "Independent units, one observation per randomized unit.",
            "Fixed-horizon analysis (a single look at the data).",
        ],
    )


def sample_size_for_means(
    std_dev: float,
    absolute_mde: float,
    alpha: float = 0.05,
    power: float = 0.8,
    allocation_ratio: float = 1.0,
    baseline_mean: float | None = None,
) -> SampleSizeResult:
    """Two-sided z-approximation sample size for a difference in means, common std dev."""
    _check_alpha_power(alpha, power)
    _check_ratio(allocation_ratio)
    if not std_dev > 0:
        raise ValueError(f"std_dev must be > 0, got {std_dev}")
    if absolute_mde == 0:
        raise ValueError("absolute_mde must be non-zero")
    r = allocation_ratio
    z = float(norm.ppf(1 - alpha / 2)) + float(norm.ppf(power))
    n_c = math.ceil(z**2 * std_dev**2 * (1 + 1 / r) / absolute_mde**2)
    n_t = math.ceil(n_c * r)
    rel = absolute_mde / baseline_mean if baseline_mean else None
    return SampleSizeResult(
        metric_type="continuous",
        n_control=n_c,
        n_treatment=n_t,
        n_total=n_c + n_t,
        alpha=alpha,
        power=power,
        absolute_mde=absolute_mde,
        relative_mde=rel,
        allocation_ratio=r,
        assumptions=[
            "Two-sided test, z approximation (slightly optimistic for very small samples).",
            "Equal standard deviation in both arms, taken from the supplied estimate.",
            "Independent units; fixed-horizon analysis.",
        ],
    )


def power_for_proportions(
    baseline: float, absolute_effect: float, n_control: int, n_treatment: int, alpha: float = 0.05
) -> float:
    """Approximate two-sided power of the pooled two-proportion z-test."""
    if n_control < 1 or n_treatment < 1:
        raise ValueError("sample sizes must be >= 1")
    p1, p2 = baseline, baseline + absolute_effect
    if not (0 < p1 < 1 and 0 < p2 < 1):
        raise ValueError("baseline and baseline + effect must lie in (0, 1)")
    p_bar = (p1 * n_control + p2 * n_treatment) / (n_control + n_treatment)
    se0 = math.sqrt(p_bar * (1 - p_bar) * (1 / n_control + 1 / n_treatment))
    se1 = math.sqrt(p1 * (1 - p1) / n_control + p2 * (1 - p2) / n_treatment)
    z_a = float(norm.ppf(1 - alpha / 2))
    d = abs(absolute_effect)
    return float(norm.cdf((d - z_a * se0) / se1) + norm.cdf((-d - z_a * se0) / se1))


def power_for_means(
    std_dev: float, absolute_effect: float, n_control: int, n_treatment: int, alpha: float = 0.05
) -> float:
    """Approximate two-sided power for a difference in means (z approximation)."""
    if n_control < 1 or n_treatment < 1:
        raise ValueError("sample sizes must be >= 1")
    if not std_dev > 0:
        raise ValueError("std_dev must be > 0")
    se = std_dev * math.sqrt(1 / n_control + 1 / n_treatment)
    z_a = float(norm.ppf(1 - alpha / 2))
    d = abs(absolute_effect) / se
    return float(norm.cdf(d - z_a) + norm.cdf(-d - z_a))


def mde_for_proportions(
    baseline: float, n_control: int, n_treatment: int, alpha: float = 0.05, power: float = 0.8
) -> float:
    """Smallest positive absolute lift detectable with the given power (bisection)."""
    _check_alpha_power(alpha, power)
    lo, hi = 1e-9, 1 - baseline - 1e-9
    if power_for_proportions(baseline, hi, n_control, n_treatment, alpha) < power:
        raise ValueError("requested power is unreachable at this sample size")
    for _ in range(80):
        mid = (lo + hi) / 2
        if power_for_proportions(baseline, mid, n_control, n_treatment, alpha) < power:
            lo = mid
        else:
            hi = mid
    return hi


def mde_for_means(
    std_dev: float, n_control: int, n_treatment: int, alpha: float = 0.05, power: float = 0.8
) -> float:
    """Smallest absolute difference in means detectable with the given power (z approximation)."""
    _check_alpha_power(alpha, power)
    if n_control < 1 or n_treatment < 1:
        raise ValueError("sample sizes must be >= 1")
    if not std_dev > 0:
        raise ValueError("std_dev must be > 0")
    z = float(norm.ppf(1 - alpha / 2)) + float(norm.ppf(power))
    return z * std_dev * math.sqrt(1 / n_control + 1 / n_treatment)


def power_curve(
    metric_type: str, absolute_effect: float, n_control_max: int, *, baseline: float = 0.0,
    std_dev: float = 1.0, alpha: float = 0.05, allocation_ratio: float = 1.0, points: int = 60,
) -> list[tuple[int, float]]:
    """Power of the fixed-horizon test at ``points`` control-arm sizes up to ``n_control_max``.

    Returns ``(n_control, power)`` pairs; the treatment arm holds ``allocation_ratio`` times
    as many units.
    """
    _check_ratio(allocation_ratio)
    if metric_type not in ("binary", "continuous"):
        raise ValueError("metric_type must be 'binary' or 'continuous'")
    if n_control_max < 2 or points < 2:
        raise ValueError("n_control_max and points must be >= 2")
    sizes = sorted({max(2, round(n_control_max * (i + 1) / points)) for i in range(points)})
    out: list[tuple[int, float]] = []
    for n_c in sizes:
        n_t = max(2, round(n_c * allocation_ratio))
        power = (power_for_proportions(baseline, absolute_effect, n_c, n_t, alpha)
                 if metric_type == "binary"
                 else power_for_means(std_dev, absolute_effect, n_c, n_t, alpha))
        out.append((n_c, power))
    return out


def duration_days(n_total: int, eligible_units_per_day: float, traffic_share: float = 1.0) -> int:
    """Days needed to enroll ``n_total`` units given explicit, constant traffic assumptions."""
    if n_total < 1:
        raise ValueError("n_total must be >= 1")
    if not eligible_units_per_day > 0:
        raise ValueError("eligible_units_per_day must be > 0")
    if not 0 < traffic_share <= 1:
        raise ValueError("traffic_share must be in (0, 1]")
    return math.ceil(n_total / (eligible_units_per_day * traffic_share))
