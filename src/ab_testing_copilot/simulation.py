"""Monte Carlo validation of the statistical procedures against known ground truth.

Every simulation is seeded and reports the Monte Carlo standard error. ``tolerance`` is
``4 * MC standard error + approximation slack`` and is fixed *before* looking at results;
a failed check means the procedure (or its stated assumptions) needs attention.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

from ab_testing_copilot.analysis import (
    FloatArray,
    adjust_pvalues,
    compare_means,
    cuped_adjust,
    ratio_core,
    two_proportion_core,
    welch_core,
)
from ab_testing_copilot.design import power_for_means, power_for_proportions
from ab_testing_copilot.models import Correction, SimulationResult, SpendingMethod
from ab_testing_copilot.sequential import (
    expected_information,
    sequential_boundaries,
    sequential_power,
)

Distribution = Literal["binary", "normal", "lognormal"]
_MAX_CELLS = 4_000_000
_SLACK: dict[str, float] = {"binary": 0.01, "normal": 0.005, "lognormal": 0.015}


def _validate(n_control: int, n_treatment: int, n_sims: int) -> None:
    if n_control < 2 or n_treatment < 2:
        raise ValueError("each arm needs at least 2 units")
    if not 100 <= n_sims <= 1_000_000:
        raise ValueError("n_sims must be between 100 and 1,000,000")


def _summaries(
    rng: np.random.Generator, dist: Distribution, n: int, n_sims: int, shift: float,
    std_dev: float,
) -> tuple[FloatArray, FloatArray]:
    """Per-simulation sample mean and variance for one arm, generated in memory-bounded chunks."""
    means, variances = np.empty(n_sims), np.empty(n_sims)
    chunk = max(1, _MAX_CELLS // n)
    for s in range(0, n_sims, chunk):
        k = min(chunk, n_sims - s)
        if dist == "normal":
            x = rng.normal(shift, std_dev, size=(k, n))
        else:  # lognormal with sigma = 1, rescaled to the requested std dev, mean = shift
            raw = rng.lognormal(0.0, 1.0, size=(k, n))
            mu, sd = math.exp(0.5), math.sqrt((math.e - 1) * math.e)
            x = (raw - mu) / sd * std_dev + shift
        means[s : s + k] = x.mean(axis=1)
        variances[s : s + k] = x.var(axis=1, ddof=1)
    return means, variances


def _run(
    dist: Distribution, n_control: int, n_treatment: int, effect: float, baseline: float,
    std_dev: float, alpha: float, n_sims: int, seed: int,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Return (p_values, ci_low, ci_high) across simulations."""
    _validate(n_control, n_treatment, n_sims)
    rng = np.random.default_rng(seed)
    if dist == "binary":
        if not (0 < baseline < 1 and 0 < baseline + effect < 1):
            raise ValueError("baseline and baseline + effect must lie in (0, 1)")
        xc = rng.binomial(n_control, baseline, size=n_sims)
        xt = rng.binomial(n_treatment, baseline + effect, size=n_sims)
        _, lo, hi, _, p = two_proportion_core(xc, n_control, xt, n_treatment, alpha)
        return p, lo, hi
    mc, vc = _summaries(rng, dist, n_control, n_sims, baseline, std_dev)
    mt, vt = _summaries(rng, dist, n_treatment, n_sims, baseline + effect, std_dev)
    _, lo, hi, _, p = welch_core(mc, vc, n_control, mt, vt, n_treatment, alpha)
    return p, lo, hi


def simulate_p_values(
    distribution: Distribution = "normal", n_control: int = 1000, n_treatment: int = 1000,
    effect: float = 0.0, baseline: float = 0.1, std_dev: float = 1.0, alpha: float = 0.05,
    n_sims: int = 5000, seed: int = 0,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Raw output of simulated experiments: ``(p_values, ci_low, ci_high)``, one per simulation.

    The rate functions below summarise exactly these arrays; this entry point exists for
    charts (for example a p-value histogram, which is flat when there is no effect).
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    if distribution not in _SLACK:
        raise ValueError(f"unknown distribution: {distribution!r}")
    if distribution != "binary" and not std_dev > 0:
        raise ValueError("std_dev must be > 0")
    return _run(distribution, n_control, n_treatment, effect, baseline, std_dev, alpha, n_sims,
                seed)


def _rate_result(
    name: str, hits: FloatArray, n_sims: int, seed: int, expected: float | None, slack: float,
    one_sided_upper: bool = False,
) -> SimulationResult:
    est = float(hits.mean())
    ref = expected if expected is not None else est
    se = math.sqrt(max(ref * (1 - ref), 1e-12) / n_sims)
    tol = 4 * se + slack if expected is not None else None
    passed: bool | None = None
    if expected is not None and tol is not None:
        passed = est <= expected + tol if one_sided_upper else abs(est - expected) <= tol
    return SimulationResult(name=name, n_sims=n_sims, seed=seed, estimate=est,
                            mc_standard_error=se, expected=expected, tolerance=tol, passed=passed)


def simulate_false_positive_rate(
    distribution: Distribution = "normal", n_control: int = 1000, n_treatment: int = 1000,
    baseline: float = 0.1, std_dev: float = 1.0, alpha: float = 0.05, n_sims: int = 5000,
    seed: int = 0,
) -> SimulationResult:
    """A/A test: share of null experiments declared significant. Expected: alpha."""
    p, _, _ = _run(distribution, n_control, n_treatment, 0.0, baseline, std_dev, alpha, n_sims,
                   seed)
    return _rate_result(f"false_positive_rate[{distribution}]", (p < alpha).astype(float),
                        n_sims, seed, alpha, _SLACK[distribution])


def simulate_power(
    effect: float, distribution: Distribution = "normal", n_control: int = 1000,
    n_treatment: int = 1000, baseline: float = 0.1, std_dev: float = 1.0, alpha: float = 0.05,
    n_sims: int = 5000, seed: int = 0,
) -> SimulationResult:
    """Share of experiments with a true effect that reach significance vs. the design formula."""
    p, _, _ = _run(distribution, n_control, n_treatment, effect, baseline, std_dev, alpha,
                   n_sims, seed)
    theory = (power_for_proportions(baseline, effect, n_control, n_treatment, alpha)
              if distribution == "binary"
              else power_for_means(std_dev, effect, n_control, n_treatment, alpha))
    res = _rate_result(f"power[{distribution}]", (p < alpha).astype(float), n_sims, seed, theory,
                       _SLACK[distribution])
    return res.model_copy(update={"details": {"type_ii_error": 1 - res.estimate}})


def simulate_coverage(
    effect: float = 0.0, distribution: Distribution = "normal", n_control: int = 1000,
    n_treatment: int = 1000, baseline: float = 0.1, std_dev: float = 1.0, alpha: float = 0.05,
    n_sims: int = 5000, seed: int = 0,
) -> SimulationResult:
    """Share of confidence intervals containing the true effect. Expected: 1 - alpha."""
    _, lo, hi = _run(distribution, n_control, n_treatment, effect, baseline, std_dev, alpha,
                     n_sims, seed)
    return _rate_result(f"ci_coverage[{distribution}]",
                        ((lo <= effect) & (effect <= hi)).astype(float), n_sims, seed, 1 - alpha,
                        _SLACK[distribution])


def simulate_peeking(
    n_per_arm: int = 1000, n_looks: int = 5, alpha: float = 0.05, correct: bool = False,
    n_sims: int = 2000, seed: int = 0,
) -> SimulationResult:
    """A/A test analysed at ``n_looks`` equally spaced interim looks, stopping at the first
    significant result. ``correct=True`` applies the Bonferroni threshold alpha / n_looks."""
    _validate(n_per_arm, n_per_arm, n_sims)
    if n_looks < 1 or n_per_arm // n_looks < 2:
        raise ValueError("need at least 2 units per arm at the first look")
    rng = np.random.default_rng(seed)
    looks = np.array([n_per_arm * (i + 1) // n_looks for i in range(n_looks)])
    threshold = alpha / n_looks if correct else alpha
    rejected = np.zeros(n_sims, dtype=bool)
    chunk = max(1, _MAX_CELLS // (2 * n_per_arm))
    for s in range(0, n_sims, chunk):
        k = min(chunk, n_sims - s)
        c, t = rng.normal(size=(k, n_per_arm)), rng.normal(size=(k, n_per_arm))
        for n in looks:
            _, _, _, _, p = welch_core(
                c[:, :n].mean(axis=1), c[:, :n].var(axis=1, ddof=1), n,
                t[:, :n].mean(axis=1), t[:, :n].var(axis=1, ddof=1), n, alpha)
            rejected[s : s + k] |= p < threshold
    name = f"peeking_fpr[looks={n_looks},{'bonferroni' if correct else 'uncorrected'}]"
    if correct:
        return _rate_result(name, rejected.astype(float), n_sims, seed, alpha, 0.0,
                            one_sided_upper=True)
    return _rate_result(name, rejected.astype(float), n_sims, seed, None, 0.0)


def simulate_multiple_testing(
    n_metrics: int = 10, method: Correction | None = None, n_per_arm: int = 500,
    alpha: float = 0.05, n_sims: int = 2000, seed: int = 0,
) -> SimulationResult:
    """Family-wise error rate when all ``n_metrics`` independent metrics are truly null."""
    if n_metrics < 1:
        raise ValueError("n_metrics must be >= 1")
    p, _, _ = _run("normal", n_per_arm, n_per_arm, 0.0, 0.0, 1.0, alpha, n_sims * n_metrics, seed)
    pm = p.reshape(n_sims, n_metrics)
    if method is None:
        any_rej = (pm < alpha).any(axis=1)
        expected = 1 - (1 - alpha) ** n_metrics
        return _rate_result(f"fwer[m={n_metrics},uncorrected]", any_rej.astype(float), n_sims,
                            seed, expected, 0.005)
    any_rej = np.array([min(adjust_pvalues(list(row), method)) < alpha for row in pm])
    return _rate_result(f"fwer[m={n_metrics},{method}]", any_rej.astype(float), n_sims, seed,
                        alpha, 0.0, one_sided_upper=True)


def simulate_cuped(
    rho: float = 0.7, effect: float = 0.1, n_per_arm: int = 500, alpha: float = 0.05,
    n_sims: int = 2000, seed: int = 0,
) -> SimulationResult:
    """CUPED with a covariate of correlation ``rho``: estimator variance ratio vs. raw.

    Expected ratio: 1 - rho^2. Also reports bias, CI coverage and power for both estimators.
    """
    if not -1 < rho < 1:
        raise ValueError("rho must be in (-1, 1)")
    _validate(n_per_arm, n_per_arm, n_sims)
    rng = np.random.default_rng(seed)
    raw, adj = np.empty(n_sims), np.empty(n_sims)
    cover = np.zeros(n_sims, dtype=bool)
    sig_raw, sig_adj = np.zeros(n_sims, dtype=bool), np.zeros(n_sims, dtype=bool)
    noise = math.sqrt(1 - rho**2)
    for i in range(n_sims):
        xc, xt = rng.normal(size=n_per_arm), rng.normal(size=n_per_arm)
        yc = rho * xc + noise * rng.normal(size=n_per_arm)
        yt = rho * xt + noise * rng.normal(size=n_per_arm) + effect
        yc_a, yt_a, _, _ = cuped_adjust(yc, xc, yt, xt)
        e_raw, e_adj = compare_means(yc, yt, alpha), compare_means(yc_a, yt_a, alpha)
        raw[i], adj[i] = e_raw.absolute_effect, e_adj.absolute_effect
        cover[i] = e_adj.ci_low <= effect <= e_adj.ci_high
        sig_raw[i], sig_adj[i] = e_raw.p_value < alpha, e_adj.p_value < alpha
    ratio = float(adj.var(ddof=1) / raw.var(ddof=1))
    expected = 1 - rho**2
    tol = 0.15 * expected + 0.01
    return SimulationResult(
        name=f"cuped_variance_ratio[rho={rho}]", n_sims=n_sims, seed=seed, estimate=ratio,
        mc_standard_error=ratio * math.sqrt(2 / (n_sims - 1)), expected=expected, tolerance=tol,
        passed=abs(ratio - expected) <= tol,
        details={"bias_cuped": float(adj.mean() - effect), "bias_raw": float(raw.mean() - effect),
                 "coverage_cuped": float(cover.mean()), "power_raw": float(sig_raw.mean()),
                 "power_cuped": float(sig_adj.mean())},
    )


def simulate_sequential(
    method: SpendingMethod = "obrien-fleming", n_looks: int = 5, n_per_arm: int = 1000,
    effect: float = 0.0, distribution: Literal["normal", "binary"] = "normal",
    baseline: float = 0.1, alpha: float = 0.05, n_sims: int = 5000, seed: int = 0,
) -> SimulationResult:
    """Group-sequential test on accumulating data: share of experiments that ever reject.

    Data arrive in ``n_looks`` equal batches; at each look the usual test (Welch or
    two-proportion z) is run on everything collected so far and compared with the Lan-DeMets
    nominal level of that look. With ``effect = 0`` the expected rate is ``alpha``; otherwise
    it is the power computed by numerical integration for a drift of ``effect / SE_final``.
    """
    _validate(n_per_arm, n_per_arm, n_sims)
    if n_looks < 1 or n_per_arm // n_looks < 2:
        raise ValueError("need at least 2 units per arm at the first look")
    if distribution not in ("normal", "binary"):
        raise ValueError("distribution must be 'normal' or 'binary'")
    looks = np.array([n_per_arm * (i + 1) // n_looks for i in range(n_looks)])
    bounds = sequential_boundaries(alpha=alpha, method=method,
                                   information_fractions=[float(n) / n_per_arm for n in looks])
    nominal = bounds.nominal_alpha
    rng = np.random.default_rng(seed)
    first = np.full(n_sims, n_looks, dtype=np.int64)  # index of the first rejecting look
    if distribution == "binary":
        if not (0 < baseline < 1 and 0 < baseline + effect < 1):
            raise ValueError("baseline and baseline + effect must lie in (0, 1)")
        steps = np.diff(looks, prepend=0)
        xc = np.cumsum(rng.binomial(steps, baseline, size=(n_sims, n_looks)), axis=1)
        xt = np.cumsum(rng.binomial(steps, baseline + effect, size=(n_sims, n_looks)), axis=1)
        for i, n in enumerate(looks):
            _, _, _, _, p = two_proportion_core(xc[:, i], n, xt[:, i], n, alpha)
            first = np.where((first == n_looks) & (p < nominal[i]), i, first)
        se_final = math.sqrt(baseline * (1 - baseline) / n_per_arm
                             + (baseline + effect) * (1 - baseline - effect) / n_per_arm)
    else:
        chunk = max(1, _MAX_CELLS // (2 * n_per_arm))
        for s in range(0, n_sims, chunk):
            k = min(chunk, n_sims - s)
            c = rng.normal(size=(k, n_per_arm))
            t = rng.normal(effect, 1.0, size=(k, n_per_arm))
            part = first[s : s + k]
            for i, n in enumerate(looks):
                _, _, _, _, p = welch_core(
                    c[:, :n].mean(axis=1), c[:, :n].var(axis=1, ddof=1), n,
                    t[:, :n].mean(axis=1), t[:, :n].var(axis=1, ddof=1), n, alpha)
                part = np.where((part == n_looks) & (p < nominal[i]), i, part)
            first[s : s + k] = part
        se_final = math.sqrt(2.0 / n_per_arm)
    rejected = first < n_looks
    drift = effect / se_final
    fractions = bounds.information_fractions
    expected = (alpha if effect == 0
                else sequential_power(bounds.critical_values, fractions, drift))
    kind = "fpr" if effect == 0 else "power"
    res = _rate_result(f"sequential_{kind}[{method},looks={n_looks},{distribution}]",
                       rejected.astype(float), n_sims, seed, expected, _SLACK[distribution])
    stop = np.array(fractions)[np.minimum(first, n_looks - 1)]
    return res.model_copy(update={"details": {
        "mean_stopping_fraction": float(stop.mean()),
        "expected_stopping_fraction": expected_information(bounds.critical_values, fractions,
                                                           drift),
        **{f"rejected_at_look_{i + 1}": float((first == i).mean()) for i in range(n_looks)},
    }})


def simulate_ratio_metric(
    analysis: Literal["delta", "rows"] = "delta", effect: float = 0.0, n_users: int = 2000,
    mean_rows: float = 20.0, baseline: float = 0.1, alpha: float = 0.05, n_sims: int = 2000,
    seed: int = 0, coverage: bool = False,
) -> SimulationResult:
    """Ratio metric with rows nested in randomised users (clicks / impressions).

    Each user has their own click propensity (Beta with mean ``baseline``) and a random number
    of impressions, so impressions of one user are correlated. ``analysis='delta'`` is the
    delta method on user-level sums and should hold ``alpha``; ``analysis='rows'`` treats every
    impression as an independent unit (the wrong unit of analysis) and is reported for
    contrast, without a pass/fail verdict. ``coverage=True`` checks the delta-method interval.
    """
    _validate(n_users, n_users, n_sims)
    if not (0 < baseline < 1 and 0 < baseline + effect < 1):
        raise ValueError("baseline and baseline + effect must lie in (0, 1)")
    if mean_rows < 1:
        raise ValueError("mean_rows must be >= 1")
    if analysis not in ("delta", "rows"):
        raise ValueError("analysis must be 'delta' or 'rows'")
    rng = np.random.default_rng(seed)
    p = np.empty(n_sims)
    lo, hi = np.empty(n_sims), np.empty(n_sims)
    chunk = max(1, _MAX_CELLS // (4 * n_users))
    b = 2.0 * (1 - baseline) / baseline
    for s in range(0, n_sims, chunk):
        k = min(chunk, n_sims - s)
        arms = []
        for shift in (0.0, effect):
            d = (1.0 + rng.poisson(mean_rows - 1, size=(k, n_users))).astype(np.float64)
            prop = np.clip(rng.beta(2.0, b, size=(k, n_users)) + shift, 0.0, 1.0)
            x = rng.binomial(d.astype(np.int64), prop).astype(np.float64)
            arms.append((x, d))
        (xc, dc), (xt, dt) = arms
        if analysis == "rows":
            _, lo_k, hi_k, _, p_k = two_proportion_core(
                xc.sum(axis=1), dc.sum(axis=1), xt.sum(axis=1), dt.sum(axis=1), alpha)
        else:
            def moments(x: FloatArray, d: FloatArray) -> tuple[FloatArray, ...]:
                mx, md = x.mean(axis=1), d.mean(axis=1)
                cov = ((x - mx[:, None]) * (d - md[:, None])).sum(axis=1) / (n_users - 1)
                return mx, md, x.var(axis=1, ddof=1), d.var(axis=1, ddof=1), cov

            mc, mt = moments(xc, dc), moments(xt, dt)
            _, lo_k, hi_k, _, p_k, _, _ = ratio_core(
                n_users, mc[0], mc[1], mc[2], mc[3], mc[4],
                n_users, mt[0], mt[1], mt[2], mt[3], mt[4], alpha)
        p[s : s + k], lo[s : s + k], hi[s : s + k] = p_k, lo_k, hi_k
    label = "delta method" if analysis == "delta" else "rows as units"
    if coverage:
        return _rate_result(f"ratio_ci_coverage[{label}]",
                            ((lo <= effect) & (effect <= hi)).astype(float), n_sims, seed,
                            1 - alpha if analysis == "delta" else None, _SLACK["binary"])
    return _rate_result(f"ratio_false_positive_rate[{label}]", (p < alpha).astype(float),
                        n_sims, seed, alpha if analysis == "delta" else None, _SLACK["binary"])


def run_validation_suite(n_sims: int = 5000, seed: int = 0) -> list[SimulationResult]:
    """Standard battery used by the CLI, the skill and the statistical tests."""
    small = max(500, n_sims // 5)
    return [
        simulate_false_positive_rate("normal", n_sims=n_sims, seed=seed),
        simulate_false_positive_rate("binary", n_control=5000, n_treatment=5000, n_sims=n_sims,
                                     seed=seed + 1),
        simulate_false_positive_rate("lognormal", n_sims=n_sims, seed=seed + 2),
        simulate_false_positive_rate("normal", n_control=400, n_treatment=1600, n_sims=n_sims,
                                     seed=seed + 3),
        simulate_power(0.125, "normal", n_sims=n_sims, seed=seed + 4),
        simulate_power(0.02, "binary", n_control=3841, n_treatment=3841, n_sims=n_sims,
                       seed=seed + 5),
        simulate_power(0.02, "binary", n_control=2000, n_treatment=6000, n_sims=n_sims,
                       seed=seed + 6),
        simulate_coverage(0.1, "normal", n_sims=n_sims, seed=seed + 7),
        simulate_coverage(0.02, "binary", n_control=5000, n_treatment=5000, n_sims=n_sims,
                          seed=seed + 8),
        simulate_coverage(0.1, "lognormal", n_sims=n_sims, seed=seed + 9),
        simulate_peeking(n_looks=5, correct=False, n_sims=small, seed=seed + 10),
        simulate_peeking(n_looks=5, correct=True, n_sims=small, seed=seed + 11),
        simulate_multiple_testing(10, None, n_sims=small, seed=seed + 12),
        simulate_multiple_testing(10, "holm", n_sims=small, seed=seed + 13),
        simulate_multiple_testing(10, "bonferroni", n_sims=small, seed=seed + 14),
        simulate_cuped(0.7, n_sims=small, seed=seed + 15),
        simulate_sequential("obrien-fleming", 5, n_sims=n_sims, seed=seed + 16),
        simulate_sequential("pocock", 5, n_sims=n_sims, seed=seed + 17),
        simulate_sequential("obrien-fleming", 4, n_per_arm=4000, distribution="binary",
                            n_sims=n_sims, seed=seed + 18),
        simulate_sequential("obrien-fleming", 5, effect=0.125, n_sims=n_sims, seed=seed + 19),
        simulate_sequential("pocock", 5, effect=0.125, n_sims=n_sims, seed=seed + 20),
        simulate_ratio_metric("delta", n_sims=n_sims, seed=seed + 21),
        simulate_ratio_metric("rows", n_sims=n_sims, seed=seed + 22),
        simulate_ratio_metric("delta", effect=0.01, coverage=True, n_sims=n_sims, seed=seed + 23),
    ]
