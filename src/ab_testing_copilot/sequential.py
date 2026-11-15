"""Group-sequential testing: Lan-DeMets alpha-spending boundaries computed numerically.

A design with ``K`` planned looks at information fractions ``t_1 < ... < t_K = 1`` spends the
two-sided type I error ``alpha`` gradually. At look ``k`` the test rejects when ``|Z_k| >= c_k``
where ``c_k`` solves

    P(|Z_1| < c_1, ..., |Z_{k-1}| < c_{k-1}, |Z_k| >= c_k | H0) = a(t_k) - a(t_{k-1})

and ``a`` is the spending function. The joint distribution of ``(Z_1, ..., Z_K)`` is the
canonical one (multivariate normal, ``Cov(Z_j, Z_k) = sqrt(t_j / t_k)`` for ``j <= k``), so the
probability is a recursive one-dimensional integral (Armitage, McPherson and Rowe 1969). It is
evaluated here with composite Gauss-Legendre quadrature on the score scale
``S_k = Z_k * sqrt(t_k)``, whose increments are independent.

Spending functions (two-sided, symmetric: half of every increment goes to each tail):

* O'Brien-Fleming type: ``a(t) = 4 - 4 * Phi(z_{alpha/4} / sqrt(t))``
* Pocock type:          ``a(t) = alpha * ln(1 + (e - 1) * t)``

These are the Lan and DeMets (1983) functions applied with ``alpha / 2`` per tail, the convention
of Stata ``gsbounds``, gsDesign and NCSS PASS, whose published values the tests reproduce.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from functools import lru_cache

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.optimize import brentq
from scipy.stats import norm

from ab_testing_copilot.analysis import FloatArray
from ab_testing_copilot.models import SequentialBoundaries, SequentialLook, SpendingMethod

MAX_LOOKS = 100
MIN_INFORMATION_GAP = 1e-3
UNDER_RUN_TOLERANCE = 0.9

_PANEL_NODES = 12  # Gauss-Legendre nodes per panel; a panel is at most one kernel SD wide
_TAIL_SIGMAS = 9.0  # the sub-density is integrated within 9 marginal SDs (mass beyond: 2e-19)
_MAX_KERNEL_CELLS = 2_000_000
_TINY = 1e-300  # an alpha increment below this cannot be represented: no stopping at that look

METHOD_LABELS: dict[str, str] = {
    "obrien-fleming": "O'Brien-Fleming-type",
    "pocock": "Pocock-type",
}

ASSUMPTIONS: tuple[str, ...] = (
    "The number of looks, their timing and the spending function were fixed before the "
    "experiment started, and the timing of a look never depends on the results seen so far.",
    "Test statistics at successive looks have independent increments with information "
    "proportional to the number of units (a large-sample result for means and proportions of "
    "independent units; the allocation ratio and the outcome variance stay constant).",
    "Boundaries are two-sided and symmetric (stop for benefit or for harm). There is no "
    "futility boundary: not crossing at an interim look means continue, not 'no effect'.",
    "The boundary is applied as a nominal significance level, 2 * (1 - Phi(c_k)), to the usual "
    "p-value and interval at that look (an approximation for t tests in small samples).",
    "Intervals at a look are repeated confidence intervals: valid at every look, wider than a "
    "fixed-horizon interval. After an early stop the point estimate overstates the effect on "
    "average; no bias-adjusted estimate is computed.",
    "Any look outside the plan voids the guarantee; analyse with n_looks (Bonferroni) instead.",
)


def sequential_assumptions(fixed_horizon: Sequence[str]) -> list[str]:
    """Assumptions of a sequential design: the fixed-horizon ones, minus 'a single look'."""
    kept = []
    for text in fixed_horizon:
        if "ixed-horizon" not in text:
            kept.append(text)
        elif text.startswith("Independent units"):
            kept.append("Independent units.")
    return kept + list(ASSUMPTIONS)


class SequentialDesign(BaseModel):
    """A pre-registered group-sequential design and the look being analysed now."""

    model_config = ConfigDict(extra="forbid")
    method: SpendingMethod
    planned_looks: int = Field(ge=1, le=MAX_LOOKS)
    current_look: int = Field(ge=1)
    information_fractions: list[float] | None = None
    planned_sample_size: int | None = Field(default=None, ge=4)

    @model_validator(mode="after")
    def _consistent(self) -> SequentialDesign:
        if self.current_look > self.planned_looks:
            raise ValueError(
                f"current_look ({self.current_look}) exceeds planned_looks "
                f"({self.planned_looks}): a look outside the plan cannot use its boundary"
            )
        if self.information_fractions is not None:
            if len(self.information_fractions) != self.planned_looks:
                raise ValueError("information_fractions needs one entry per planned look")
            fractions = _check_information(self.information_fractions)
            if abs(float(fractions[-1]) - 1.0) > 1e-9:
                raise ValueError("the last planned information fraction must be 1")
        return self

    def planned_fractions(self) -> list[float]:
        if self.information_fractions is not None:
            return [float(t) for t in self.information_fractions]
        return [j / self.planned_looks for j in range(1, self.planned_looks + 1)]


def _check_alpha(alpha: float) -> None:
    if not (isinstance(alpha, int | float) and 0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")


def _check_information(information: Sequence[float]) -> FloatArray:
    t = np.asarray(information, dtype=np.float64).ravel()
    if t.size < 1 or t.size > MAX_LOOKS:
        raise ValueError(f"the number of looks must be between 1 and {MAX_LOOKS}, got {t.size}")
    if not np.isfinite(t).all() or (t <= 0).any():
        raise ValueError("information fractions must be finite and > 0")
    if t.size > 1 and (np.diff(t) < MIN_INFORMATION_GAP).any():
        raise ValueError(
            "information fractions must increase by at least "
            f"{MIN_INFORMATION_GAP:g} from one look to the next"
        )
    return t


def equal_fractions(n_looks: int) -> list[float]:
    """Information fractions of ``n_looks`` equally spaced looks."""
    if not 1 <= n_looks <= MAX_LOOKS:
        raise ValueError(f"the number of looks must be between 1 and {MAX_LOOKS}, got {n_looks}")
    return [j / n_looks for j in range(1, n_looks + 1)]


def alpha_spent(
    information_fraction: float, alpha: float = 0.05, method: SpendingMethod = "obrien-fleming"
) -> float:
    """Cumulative two-sided type I error spent by ``information_fraction`` (capped at 1)."""
    _check_alpha(alpha)
    t = float(information_fraction)
    if not (math.isfinite(t) and t > 0):
        raise ValueError(f"information_fraction must be > 0, got {information_fraction}")
    if t >= 1:
        return alpha
    if method == "obrien-fleming":
        return min(alpha, 4 * float(norm.sf(float(norm.isf(alpha / 4)) / math.sqrt(t))))
    if method == "pocock":
        return min(alpha, alpha * math.log1p((math.e - 1) * t))
    raise ValueError(f"unknown spending method: {method!r} (use 'obrien-fleming' or 'pocock')")


@lru_cache(maxsize=4)
def _panel_rule(n: int) -> tuple[FloatArray, FloatArray]:
    nodes, weights = np.polynomial.legendre.leggauss(n)
    return np.asarray(nodes, dtype=np.float64), np.asarray(weights, dtype=np.float64)


def _grid(lo: float, hi: float, scale: float, resolution: int) -> tuple[FloatArray, FloatArray]:
    """Composite Gauss-Legendre nodes and weights on [lo, hi]; panels are <= ``scale`` wide."""
    panels = max(4, math.ceil(resolution * (hi - lo) / scale))
    edges = np.linspace(lo, hi, panels + 1)
    nodes, weights = _panel_rule(_PANEL_NODES)
    half = (edges[1:] - edges[:-1]) / 2
    mid = (edges[1:] + edges[:-1]) / 2
    x = (mid[:, None] + half[:, None] * nodes[None, :]).ravel()
    w = (half[:, None] * weights[None, :]).ravel()
    return x, w


class _Path:
    """Sub-density of the score statistic among paths that have not crossed a boundary."""

    def __init__(self, information: FloatArray, drift: float, resolution: int) -> None:
        self.t = information
        self.drift = drift
        self.resolution = resolution
        self.k = 0  # number of looks already passed
        self.x: FloatArray = np.empty(0)
        self.g: FloatArray = np.empty(0)  # quadrature weight * sub-density at ``x``

    def _step(self) -> tuple[float, float]:
        """Mean shift and standard deviation of the score increment into the next look."""
        prev = self.t[self.k - 1] if self.k else 0.0
        d = float(self.t[self.k] - prev)
        return self.drift * d, math.sqrt(d)

    def tails(self, critical_value: float) -> tuple[float, float]:
        """P(first exit below -c, first exit above +c) at the next look."""
        if not math.isfinite(critical_value):
            return 0.0, 0.0
        shift, sd = self._step()
        b = critical_value * math.sqrt(float(self.t[self.k]))
        if self.k == 0:
            return float(norm.cdf((-b - shift) / sd)), float(norm.sf((b - shift) / sd))
        mean = self.x + shift
        lower = float(self.g @ norm.cdf((-b - mean) / sd))
        upper = float(self.g @ norm.sf((b - mean) / sd))
        return lower, upper

    def advance(self, critical_value: float) -> None:
        """Move past the next look, keeping only paths inside (-c, c)."""
        shift, sd = self._step()
        t_k = float(self.t[self.k])
        centre, spread = self.drift * t_k, math.sqrt(t_k)
        b = critical_value * spread
        lo = max(-b, centre - _TAIL_SIGMAS * spread)
        hi = min(b, centre + _TAIL_SIGMAS * spread)
        if not hi > lo:  # every path has left the continuation region
            self.x, self.g = np.empty(0), np.empty(0)
            self.k += 1
            return
        scale = sd
        if self.k + 1 < self.t.size:
            scale = min(sd, math.sqrt(float(self.t[self.k + 1] - t_k)))
        x_new, w_new = _grid(lo, hi, scale, self.resolution)
        if self.k == 0:
            dens = norm.pdf((x_new - shift) / sd) / sd
        else:
            mean = self.x + shift
            dens = np.empty(x_new.size)
            rows = max(1, _MAX_KERNEL_CELLS // max(1, mean.size))
            for s in range(0, x_new.size, rows):
                z = (x_new[s : s + rows, None] - mean[None, :]) / sd
                dens[s : s + rows] = (norm.pdf(z) / sd) @ self.g
        self.x, self.g = x_new, w_new * dens
        self.k += 1


def exit_probabilities(
    critical_values: Sequence[float], information_fractions: Sequence[float],
    drift: float = 0.0, resolution: int = 1,
) -> tuple[list[float], list[float]]:
    """Probability of first crossing ``-c_k`` and ``+c_k`` at each look: ``(lower, upper)``.

    ``drift`` is the expected z statistic at information fraction 1; at fraction ``t`` the
    expectation is ``drift * sqrt(t)``. ``drift = 0`` is the null hypothesis.
    """
    t = _check_information(information_fractions)
    c = np.asarray(critical_values, dtype=np.float64).ravel()
    if c.size != t.size:
        raise ValueError("critical_values and information_fractions must have the same length")
    if np.isnan(c).any() or (c < 0).any():
        raise ValueError("critical values must be >= 0 (use inf for a look without stopping)")
    if not math.isfinite(drift):
        raise ValueError("drift must be finite")
    if resolution < 1:
        raise ValueError("resolution must be >= 1")
    path = _Path(t, float(drift), resolution)
    lower: list[float] = []
    upper: list[float] = []
    for k in range(t.size):
        lo, up = path.tails(float(c[k]))
        lower.append(lo)
        upper.append(up)
        if k + 1 < t.size:
            path.advance(float(c[k]))
    return lower, upper


def boundaries_from_spending(
    cumulative_alpha: Sequence[float], information_fractions: Sequence[float],
    resolution: int = 1,
) -> list[float]:
    """Symmetric two-sided critical values that spend ``cumulative_alpha`` look by look.

    ``cumulative_alpha[k]`` is the total two-sided type I error allowed through look ``k``.
    ``information_fractions`` set the correlation between looks and may be any increasing
    positive numbers (only their ratios matter under the null hypothesis).
    """
    t = _check_information(information_fractions)
    a = np.asarray(cumulative_alpha, dtype=np.float64).ravel()
    if a.size != t.size:
        raise ValueError("cumulative_alpha and information_fractions must have the same length")
    if not np.isfinite(a).all() or (a < 0).any() or (a >= 1).any() or (np.diff(a) < 0).any():
        raise ValueError("cumulative_alpha must be non-decreasing and within [0, 1)")
    if resolution < 1:
        raise ValueError("resolution must be >= 1")
    path = _Path(t, 0.0, resolution)
    crit: list[float] = []
    spent = 0.0
    for k in range(t.size):
        target = (float(a[k]) - spent) / 2  # upper-tail first-exit probability at this look
        spent = float(a[k])
        if target < _TINY:
            c = math.inf
        elif k == 0:
            c = float(norm.isf(target))
        else:
            log_target = math.log(target)

            def gap(value: float, _log_target: float = log_target) -> float:
                tail = path.tails(value)[1]
                return math.log(tail) - _log_target if tail > 0 else -1e30

            # P(first exit above c) <= P(Z_k >= c), so isf(target) is a valid upper bracket.
            c = float(brentq(gap, 0.0, float(norm.isf(target)) + 1e-9, xtol=1e-13, rtol=1e-14))
        crit.append(c)
        if k + 1 < t.size:
            path.advance(c)
    return crit


def sequential_boundaries(
    n_looks: int | None = None, alpha: float = 0.05, method: SpendingMethod = "obrien-fleming",
    information_fractions: Sequence[float] | None = None,
) -> SequentialBoundaries:
    """Lan-DeMets boundaries for a planned design (equally spaced looks unless fractions given)."""
    _check_alpha(alpha)
    if information_fractions is None:
        if n_looks is None:
            raise ValueError("give n_looks or information_fractions")
        fractions = equal_fractions(n_looks)
    else:
        fractions = [float(v) for v in _check_information(information_fractions)]
        if n_looks is not None and n_looks != len(fractions):
            raise ValueError("n_looks does not match the number of information fractions")
        if abs(fractions[-1] - 1.0) > 1e-9:
            raise ValueError("the last planned information fraction must be 1")
        if fractions[-1] != 1.0:
            fractions[-1] = 1.0
    cumulative = [alpha_spent(t, alpha, method) for t in fractions]
    crit = boundaries_from_spending(cumulative, fractions)
    return SequentialBoundaries(
        method=method, alpha=alpha, information_fractions=fractions, critical_values=crit,
        nominal_alpha=[2 * float(norm.sf(c)) for c in crit], cumulative_alpha=cumulative,
        assumptions=list(ASSUMPTIONS),
    )


def sequential_power(
    critical_values: Sequence[float], information_fractions: Sequence[float], drift: float
) -> float:
    """Probability of crossing either boundary at any look when the expected final z is ``drift``.

    As in the fixed-horizon power functions, rejections in both directions are counted.
    """
    lower, upper = exit_probabilities(critical_values, information_fractions, drift)
    return float(min(1.0, sum(lower) + sum(upper)))


def expected_information(
    critical_values: Sequence[float], information_fractions: Sequence[float], drift: float
) -> float:
    """Expected information fraction at which the design stops (the last look if it never does)."""
    t = [float(v) for v in information_fractions]
    lower, upper = exit_probabilities(critical_values, t, drift)
    stop = [lo + up for lo, up in zip(lower, upper, strict=True)]
    stay = max(0.0, 1.0 - sum(stop))
    return float(sum(p * f for p, f in zip(stop[:-1], t[:-1], strict=True))
                 + (stop[-1] + stay) * t[-1])


def fixed_horizon_drift(alpha: float, power: float) -> float:
    """Expected z at which a single two-sided test at level ``alpha`` reaches ``power``."""
    _check_alpha(alpha)
    if not alpha < power < 1:
        raise ValueError(f"power must be in (alpha, 1), got {power}")
    z_a = float(norm.isf(alpha / 2))

    def gap(d: float) -> float:
        return float(norm.cdf(d - z_a) + norm.cdf(-d - z_a)) - power

    return float(brentq(gap, 0.0, z_a + float(norm.isf(1 - power)) + 10.0, xtol=1e-12))


def required_drift(boundaries: SequentialBoundaries, power: float) -> float:
    """Expected final z at which the sequential design reaches ``power``."""
    if not boundaries.alpha < power < 1:
        raise ValueError(f"power must be in (alpha, 1), got {power}")
    crit, t = boundaries.critical_values, boundaries.information_fractions

    def gap(d: float) -> float:
        return sequential_power(crit, t, d) - power

    hi = float(norm.isf(boundaries.alpha / 2)) + float(norm.isf(1 - power)) + 10.0
    return float(brentq(gap, 0.0, hi, xtol=1e-10))


def inflation_factor(boundaries: SequentialBoundaries, power: float = 0.8) -> float:
    """Maximum sample size of the sequential design relative to a fixed-horizon test.

    Both designs have the same two-sided ``alpha`` and the same ``power`` for the same effect.
    """
    return (required_drift(boundaries, power) / fixed_horizon_drift(boundaries.alpha, power)) ** 2


def sequential_look(
    design: SequentialDesign, alpha: float = 0.05, n_observed: int | None = None
) -> SequentialLook:
    """Critical value for the look being analysed.

    Earlier looks are taken at their planned information fractions. When the design carries a
    ``planned_sample_size`` and ``n_observed`` is given, the current look uses the observed
    fraction ``n_observed / planned_sample_size`` (the Lan-DeMets rule): alpha is spent for the
    information actually collected. The final look always spends everything that is left.
    """
    _check_alpha(alpha)
    k, total = design.current_look, design.planned_looks
    planned = design.planned_fractions()
    spend, info = planned[:k], planned[:k]
    is_final = k == total
    notes: list[str] = []
    warnings: list[str] = []
    observed: float | None = None
    if design.planned_sample_size is not None and n_observed is not None:
        if n_observed < 1:
            raise ValueError("n_observed must be >= 1")
        observed = n_observed / design.planned_sample_size
        previous = planned[k - 2] if k > 1 else 0.0
        if observed - previous < MIN_INFORMATION_GAP:
            raise ValueError(
                f"look {k} holds {observed:.1%} of the planned sample, which is not above the "
                f"{previous:.1%} planned for the previous look; pass the information fractions "
                "of the looks that were actually taken"
            )
        if observed >= 1.0 and not is_final:
            is_final = True
            notes.append(
                f"The planned maximum sample was reached at look {k} of {total}; this look is "
                "treated as the final analysis and spends all remaining alpha."
            )
        if is_final:
            spend, info = [*spend[:-1], 1.0], [*info[:-1], observed]
            if observed < UNDER_RUN_TOLERANCE:
                warnings.append(
                    f"The final analysis holds {observed:.1%} of the pre-registered sample. The "
                    "error rate is controlled only if no further data are analysed, and power "
                    "is below the design."
                )
            elif abs(observed - 1.0) > 1e-9:
                notes.append(
                    f"The final analysis holds {observed:.1%} of the pre-registered sample; the "
                    "boundary uses the observed information ratios."
                )
        else:
            spend, info = [*spend[:-1], observed], [*info[:-1], observed]
            if abs(observed - planned[k - 1]) > 0.1 * planned[k - 1]:
                notes.append(
                    f"Look {k} was planned at {planned[k - 1]:.1%} of the sample but holds "
                    f"{observed:.1%}; alpha is spent for the observed fraction."
                )
    else:
        notes.append(
            "The information fraction is taken from the plan; it was not checked against the "
            "data because no planned_sample_size was declared."
        )
    cumulative = [alpha_spent(t, alpha, design.method) for t in spend]
    crit = boundaries_from_spending(cumulative, info)
    return SequentialLook(
        method=design.method, planned_looks=total, current_look=k, is_final=is_final,
        information_fraction=spend[-1], observed_fraction=observed,
        critical_value=crit[-1], nominal_alpha=2 * float(norm.sf(crit[-1])),
        cumulative_alpha=cumulative[-1], overall_alpha=alpha,
        plan=sequential_boundaries(alpha=alpha, method=design.method,
                                   information_fractions=planned),
        notes=notes, warnings=warnings,
    )
