#!/usr/bin/env python3
"""Print the statistical evidence quoted in QUALITY_REPORT.md.

    python benchmarks/statistical_evidence.py

Four tables: computed group-sequential values next to the published ones, the Monte Carlo
quantities that tests/statistical/test_feature_monte_carlo.py asserts on (same seeds, same
generators, so the numbers printed here are the numbers those tests see), the A/A check on
independent and on clustered data, and the novelty check run on whole synthetic experiments
whose effect does not change over time. Takes about a minute and a half.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

try:
    import ab_testing_copilot  # noqa: F401
except ModuleNotFoundError:  # running from a repository checkout without installation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from scipy.stats import multivariate_normal, norm

from ab_testing_copilot import heterogeneity as ht
from ab_testing_copilot import novelty as nv
from ab_testing_copilot import sequential as sq
from ab_testing_copilot.aa import aa_check
from ab_testing_copilot.analysis import compare_proportions
from ab_testing_copilot.experiment import ExperimentConfig, MetricSpec, analyze_experiment
from ab_testing_copilot.models import Decision, PeriodEffect
from ab_testing_copilot.sequential import SequentialDesign
from ab_testing_copilot.synthetic import make_experiment, make_sessions


def _total(crit: list[float], fractions: list[float], drift: float = 0.0) -> float:
    lower, upper = sq.exit_probabilities(crit, fractions, drift)
    return sum(lower) + sum(upper)


def _fmt(values: list[float], digits: int = 4) -> str:
    return ", ".join(f"{v:.{digits}f}" for v in values)


def published() -> list[str]:
    obf5 = sq.sequential_boundaries(5, 0.05, "obrien-fleming")
    obf4 = sq.sequential_boundaries(4, 0.05, "obrien-fleming")
    poc4 = sq.sequential_boundaries(4, 0.05, "pocock")
    kd_equal = sq.boundaries_from_spending([0.05 * t**3 for t in (1 / 3, 2 / 3, 1.0)],
                                           [1 / 3, 2 / 3, 1.0])
    kd_uneven = sq.boundaries_from_spending([0.05 * t**3 for t in (1 / 3, 0.5, 2 / 3, 1.0)],
                                            [1 / 3, 0.5, 2 / 3, 1.0])
    t5 = sq.equal_fractions(5)
    obf = [2.040 * math.sqrt(5 / k) for k in range(1, 6)]
    z = float(norm.isf(0.025))
    drift = (norm.isf(0.025) + norm.isf(0.2))
    rows = [
        ("O'Brien-Fleming type, 5 looks", _fmt(obf5.critical_values, 6),
         "4.8769, 3.3570, 2.6803, 2.2898, 2.0310 (Stata); 3.3569 at look 2 (NCSS)"),
        ("O'Brien-Fleming type, 4 looks", _fmt(obf4.critical_values, 6),
         "4.333, 2.963, 2.359, 2.014 (gsDesign)"),
        ("Pocock type, 4 looks", _fmt(poc4.critical_values, 6),
         "2.368328, 2.367524, 2.358168, 2.350030 (gsDesign)"),
        ("Kim-DeMets t^3, 3 equal looks", _fmt(kd_equal), "3.1130, 2.4619, 2.0087 (Stata)"),
        ("Kim-DeMets t^3, looks at 1/3, 1/2, 2/3, 1", _fmt(kd_uneven),
         "3.1130, 2.7889, 2.5133, 2.0120 (Stata)"),
        ("Inflation factor, O'Brien-Fleming type, 5 looks, power 0.8",
         f"{sq.inflation_factor(obf5, 0.8):.6f}", "1.0247 (Stata)"),
        ("Overall alpha of the classical Pocock constant 2.413, 5 looks",
         f"{_total([2.413] * 5, t5):.6f}", "0.05 (Jennison & Turnbull)"),
        ("Overall alpha of the classical O'Brien-Fleming constant 2.040, 5 looks",
         f"{_total(obf, t5):.6f}", "0.05 (Jennison & Turnbull)"),
        ("Power of classical Pocock at sample-size ratio 1.229",
         f"{sq.sequential_power([2.413] * 5, t5, math.sqrt(1.229) * drift):.4f}",
         "0.8 (Jennison & Turnbull)"),
        ("Power of classical O'Brien-Fleming at sample-size ratio 1.028",
         f"{sq.sequential_power(obf, t5, math.sqrt(1.028) * drift):.4f}",
         "0.8 (Jennison & Turnbull)"),
        ("Overall error of a 5% test repeated at 2, 3, 4, 5, 10 looks",
         _fmt([_total([z] * k, sq.equal_fractions(k)) for k in (2, 3, 4, 5, 10)]),
         "0.083, 0.107, 0.126, 0.142, 0.193 (Armitage, McPherson & Rowe)"),
    ]
    for method in ("obrien-fleming", "pocock"):
        b = sq.sequential_boundaries(4, 0.05, method)
        t, c = np.array(b.information_fractions), np.array(b.critical_values)
        cov = np.sqrt(np.minimum.outer(t, t) / np.maximum.outer(t, t))
        stay = multivariate_normal(mean=np.zeros(4), cov=cov, seed=0, abseps=1e-9,
                                   releps=1e-9, maxpts=4_000_000).cdf(c, lower_limit=-c)
        rows.append((f"Overall alpha by scipy multivariate normal, {method}, 4 looks",
                     f"{1 - stay:.8f}", "0.05 (design value)"))
    return ["| Quantity | Computed | Published or design value |", "|---|---|---|",
            *[f"| {a} | {b} | {c} |" for a, b, c in rows]]


def _daily(rng: np.random.Generator, lifts: list[float], n: int) -> list[PeriodEffect]:
    out = []
    for day, lift in enumerate(lifts):
        xc, xt = rng.binomial(n, 0.10), rng.binomial(n, 0.10 + lift)
        e = compare_proportions(int(xc), n, int(xt), n)
        out.append(PeriodEffect(index=day, label=str(day), n_control=n, n_treatment=n,
                                effect=e.absolute_effect, std_error=float(e.std_error or 0)))
    return out


def _segments(rng: np.random.Generator, lifts: list[float], correction: str = "holm"):
    est, wide = {}, {}
    for i, lift in enumerate(lifts):
        xc, xt = int(rng.binomial(2000, 0.10)), int(rng.binomial(2000, 0.10 + lift))
        est[f"s{i}"] = compare_proportions(xc, 2000, xt, 2000)
        wide[f"s{i}"] = compare_proportions(xc, 2000, xt, 2000, 0.05 / len(lifts))
    return ht.summarise_segments(est, wide, "segment", 0.05, correction)  # type: ignore[arg-type]


def monte_carlo() -> list[str]:
    def upper(rate: float, n: int) -> float:
        return rate + 4 * math.sqrt(rate * (1 - rate) / n) + 0.01

    rows: list[tuple[str, str, str]] = []
    cfg = ExperimentConfig(primary=MetricSpec(column="converted", type="binary"))

    def run(lift: float, seeds: range) -> tuple[int, int, int]:
        shipped = early = other = 0
        for seed in seeds:
            df = make_experiment(n=2000, lift=lift, seed=seed)
            for k in range(1, 5):
                design = SequentialDesign(method="obrien-fleming", planned_looks=4,
                                          current_look=k, planned_sample_size=2000)
                r = analyze_experiment(df.iloc[: 500 * k],
                                       cfg.model_copy(update={"sequential": design}))
                if r.decision is Decision.SHIP:
                    shipped += 1
                    early += k < 4
                    break
                if r.decision is Decision.DO_NOT_SHIP:
                    other += 1
                    break
        return shipped, early, other

    ship, _, harm = run(0.0, range(1000, 1250))
    rows.append(("Decision engine, 4 O'Brien-Fleming looks, no effect: share of 250 "
                 "experiments with any Ship or Do not ship", f"{(ship + harm) / 250:.3f}",
                 f"at most {upper(0.05, 250):.3f}"))
    ship, early, harm = run(0.05, range(2000, 2100))
    rows.append(("Same design, true lift +5 pp: Ship / stopped before the last look / Do not "
                 "ship, out of 100", f"{ship} / {early} / {harm}",
                 "at least 80 / at least 40 / 0"))
    rng = np.random.default_rng(21)
    res = [nv.assess_novelty(_daily(rng, [0.02] * 14, 500)) for _ in range(400)]
    decay = sum(r.decay_detected for r in res) / 400
    trend = sum(r.decay_detected or r.growth_detected or r.reversal_detected
                for r in res) / 400
    rows.append(("Novelty check, constant effect, 400 simulations: any significant trend",
                 f"{trend:.4f}", f"at most {upper(0.05, 400):.4f}"))
    rows.append(("Novelty check, constant effect: decay warnings", f"{decay:.4f}",
                 f"at most {upper(0.025, 400):.4f}"))
    rng = np.random.default_rng(22)
    lifts = [0.06 * 0.5 ** (d / 3) for d in range(14)]
    hits = sum(nv.assess_novelty(_daily(rng, lifts, 2000)).decay_detected for _ in range(200))
    rows.append(("Novelty check, lift halving every 3 days, 200 simulations: decay detected",
                 f"{hits / 200:.3f}", "at least 0.9"))
    for correction in ("holm", "bonferroni", "benjamini-hochberg"):
        rng = np.random.default_rng(23)
        runs = [_segments(rng, [0.0] * 5, correction) for _ in range(400)]
        flag = sum(any(s.significant_after_correction for s in r.segments) for r in runs) / 400
        rows.append((f"Segments, no effect anywhere, 5 segments, {correction}: any segment "
                     "flagged, 400 simulations", f"{flag:.4f}",
                     f"at most {upper(0.05, 400):.4f}"))
        if correction == "holm":
            cover = sum(all(s.simultaneous_ci_low <= 0 <= s.simultaneous_ci_high
                            for s in r.segments) for r in runs) / 400
            rows.append(("Segments: all five simultaneous intervals cover zero",
                         f"{cover:.4f}",
                         f"at least {0.95 - 4 * math.sqrt(0.05 * 0.95 / 400) - 0.01:.4f}"))
    rng = np.random.default_rng(24)
    same = sum(_segments(rng, [0.02] * 5).heterogeneity_detected for _ in range(400)) / 400
    slack = 4 * math.sqrt(0.05 * 0.95 / 400) + 0.01
    rows.append(("Cochran's Q, equal effects in 5 segments, 400 simulations: rejections",
                 f"{same:.4f}", f"0.05 within {slack:.4f}"))
    differ = sum(_segments(rng, [0, 0, 0, 0, 0.05]).heterogeneity_detected
                 for _ in range(200)) / 200
    rows.append(("Cochran's Q, one segment with +5 pp, 200 simulations: rejections",
                 f"{differ:.3f}", "at least 0.9"))
    return ["| Check | Observed | Threshold set before the run |", "|---|---|---|",
            *[f"| {a} | {b} | {c} |" for a, b, c in rows]]


def aa() -> list[str]:
    units = make_experiment(n=6000)
    sessions = make_sessions(n_users=1500, seed=5)
    sessions["ctr"] = sessions["clicks"] / sessions["impressions"]
    cases = [
        ("6,000 independent users, binary metric, z test",
         aa_check(units, "converted", "binary", n_relabels=1000, seed=3)),
        ("Session rows of 1,500 users, users re-labelled, Welch test on rows",
         aa_check(sessions, "ctr", "continuous", unit_col="user_id", n_relabels=500, seed=1)),
        ("Same sessions, delta-method ratio metric on user sums",
         aa_check(sessions, "clicks", "ratio", denominator="impressions", unit_col="user_id",
                  n_relabels=500, seed=1)),
    ]
    return ["| Data and analysis | False-positive rate at alpha 0.05 | Verdict |", "|---|---|---|",
            *[f"| {name} | {r.false_positive_rate:.3f} | {r.verdict} |" for name, r in cases]]


def novelty_on_datasets() -> list[str]:
    """How often the novelty check speaks up when the effect is constant by construction.

    No threshold was fixed for this table in advance: it was added after the default seed of
    the built-in sample ratio mismatch scenario showed a novelty warning, to tell a chance alarm
    from a systematic one. The natural bound is the level of the trend test, 0.05.
    """
    cfg = ExperimentConfig(primary=MetricSpec(column="converted", type="binary"),
                           unit_col="user_id", date_col="exposure_date")
    cases: list[tuple[str, dict[str, float]]] = [
        ("Constant lift of +1.5 pp", {}),
        ("No effect", {"lift": 0.0}),
        ("No effect, 15% of non-converting control users lost (sample ratio mismatch scenario)",
         {"lift": 0.0, "srm_drop": 0.15}),
    ]
    seeds = range(1000, 1300)
    rows = []
    for name, kwargs in cases:
        found = [analyze_experiment(make_experiment(seed=seed, **kwargs), cfg).novelty
                 for seed in seeds]
        n = len(found)
        rows.append((name,
                     f"{sum(r.p_value < 0.05 for r in found) / n:.3f}",
                     f"{sum(r.decay_detected for r in found) / n:.3f}",
                     f"{sum(r.growth_detected for r in found) / n:.3f}",
                     f"{sum(r.reversal_detected for r in found) / n:.3f}"))
    return ["| Data (300 datasets of 20,000 users each, seeds 1000 to 1299) | Trend p < 0.05 "
            "| Decay warning | Growth | Reversal |", "|---|---|---|---|---|",
            *[f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in rows]]


def main() -> int:
    for title, table in (("Group-sequential values against published values", published()),
                         ("Monte Carlo checks of the new features", monte_carlo()),
                         ("A/A check", aa()),
                         ("Novelty check on whole datasets with a constant effect",
                          novelty_on_datasets())):
        print(f"## {title}\n")
        print("\n".join(table))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
