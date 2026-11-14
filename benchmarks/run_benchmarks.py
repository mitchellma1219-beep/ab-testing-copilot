#!/usr/bin/env python3
"""Measure how long the main operations take, on synthetic data.

    python benchmarks/run_benchmarks.py                 # full sizes, about a minute
    python benchmarks/run_benchmarks.py --quick         # small sizes, a few seconds
    python benchmarks/run_benchmarks.py --out results   # also write results/benchmarks.{json,md}

Each operation runs ``--repeats`` times; the table reports the fastest and the median run
(wall clock, ``time.perf_counter``) and, where it is cheap to measure, the peak of additional
Python memory (``tracemalloc``, measured in a separate run because tracing slows the code).
Timings depend on the machine and on what else it is doing: read them as orders of magnitude.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path

try:
    import ab_testing_copilot
except ModuleNotFoundError:  # running from a repository checkout without installation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import ab_testing_copilot

import numpy as np
import pandas as pd
import scipy

from ab_testing_copilot import analysis, simulation
from ab_testing_copilot import sequential as seq
from ab_testing_copilot.aa import aa_check
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
)
from ab_testing_copilot.synthetic import make_experiment, make_sessions
from ab_testing_copilot.units import aggregate_to_units

REVENUE = MetricSpec(column="revenue", type="continuous")
CONVERTED = MetricSpec(column="converted", type="binary")
LOAD = GuardrailSpec(column="page_load_ms", type="continuous", higher_is_better=False)
CTR = MetricSpec(column="clicks", type="ratio", denominator="impressions")


def measure(fn: Callable[[], object], repeats: int, memory: bool) -> dict[str, float | None]:
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    peak_mb: float | None = None
    if memory:
        tracemalloc.start()
        fn()
        peak_mb = tracemalloc.get_traced_memory()[1] / 1e6
        tracemalloc.stop()
    return {"best_s": min(times), "median_s": statistics.median(times), "peak_mb": peak_mb}


def cases(quick: bool) -> list[tuple[str, Callable[[], object], bool]]:
    """(name, callable, measure memory). Data are generated before timing starts."""
    sizes = [2_000, 10_000] if quick else [10_000, 100_000, 1_000_000]
    out: list[tuple[str, Callable[[], object], bool]] = []
    for n in sizes:
        df = make_experiment(n=n, revenue_effect=0.5)
        cuped = ExperimentConfig(primary=REVENUE, guardrails=[LOAD], unit_col="user_id",
                                 covariate_col="pre_spend")
        out.append((f"analyze_experiment, {n:,} rows: CUPED + 1 guardrail",
                    lambda df=df, cfg=cuped: analyze_experiment(df, cfg), True))
    n_mid = sizes[-2] if not quick else sizes[-1]
    df = make_experiment(n=n_mid)
    full = ExperimentConfig(
        primary=CONVERTED, guardrails=[LOAD], unit_col="user_id", date_col="exposure_date",
        segment_col="segment",
        sequential=seq.SequentialDesign(method="obrien-fleming", planned_looks=5,
                                        current_look=3))
    out.append((f"analyze_experiment, {n_mid:,} rows: sequential look + novelty + segments",
                lambda df=df, cfg=full: analyze_experiment(df, cfg), True))
    for looks in ([5, 20] if quick else [5, 20, 100]):
        out.append((f"sequential_boundaries, {looks} looks (O'Brien-Fleming type)",
                    lambda k=looks: seq.sequential_boundaries(k, 0.05, "obrien-fleming"), False))
    bounds = seq.sequential_boundaries(5, 0.05, "pocock")
    out.append(("inflation_factor, 5 looks (Pocock type, power 0.8)",
                lambda b=bounds: seq.inflation_factor(b, 0.8), False))
    n_aa, relabels = (5_000, 200) if quick else (20_000, 1000)
    units = make_experiment(n=n_aa)
    out.append((f"aa_check, {relabels:,} re-labellings of {n_aa:,} units (binary)",
                lambda d=units, r=relabels: aa_check(d, "converted", "binary", n_relabels=r),
                False))
    n_users = 2_000 if quick else 200_000
    sessions = make_sessions(n_users=n_users)
    out.append((f"aggregate_to_units, {len(sessions):,} session rows -> {n_users:,} users",
                lambda s=sessions: aggregate_to_units(
                    s, "user_id", {"clicks": "sum", "impressions": "sum"}), True))
    users = aggregate_to_units(sessions, "user_id", {"clicks": "sum", "impressions": "sum"})
    ratio = ExperimentConfig(primary=CTR, unit_col="user_id")
    out.append((f"analyze_experiment, ratio metric (delta method), {n_users:,} users",
                lambda u=users, cfg=ratio: analyze_experiment(u, cfg), True))
    rng = np.random.default_rng(0)
    n_boot, resamples = (5_000, 200) if quick else (100_000, 2000)
    c, t = rng.normal(0, 1, n_boot), rng.normal(0.02, 1, n_boot)
    out.append((f"bootstrap_mean_diff, {resamples:,} resamples x {n_boot:,} per arm",
                lambda: analysis.bootstrap_mean_diff(c, t, n_boot=resamples), False))
    n_sims = 500 if quick else 5000
    out.append((f"run_validation_suite, {n_sims:,} simulations (24 checks)",
                lambda: simulation.run_validation_suite(n_sims, 0), False))
    return out


def environment() -> dict[str, object]:
    return {
        "python": platform.python_version(), "platform": platform.platform(),
        "cpu_count": os.cpu_count(), "numpy": np.__version__, "scipy": scipy.__version__,
        "pandas": pd.__version__, "ab_testing_copilot": ab_testing_copilot.__version__,
    }


def render(results: list[dict[str, object]], env: dict[str, object], repeats: int) -> str:
    lines = ["| Operation | Best | Median | Peak additional memory |", "|---|---|---|---|"]
    for r in results:
        peak = "not measured" if r["peak_mb"] is None else f"{r['peak_mb']:.0f} MB"
        lines.append(f"| {r['name']} | {_fmt(float(r['best_s']))} | "  # type: ignore[arg-type]
                     f"{_fmt(float(r['median_s']))} | {peak} |")  # type: ignore[arg-type]
    lines += ["", f"{repeats} run(s) per operation. Python {env['python']}, numpy "
              f"{env['numpy']}, scipy {env['scipy']}, pandas {env['pandas']}, "
              f"{env['cpu_count']} CPU(s), {env['platform']}."]
    return "\n".join(lines)


def _fmt(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms" if seconds < 1 else f"{seconds:.2f} s"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="small sizes (seconds, for a smoke run)")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", type=Path, help="directory for benchmarks.json and benchmarks.md")
    args = ap.parse_args(argv)
    if args.repeats < 1:
        ap.error("--repeats must be >= 1")
    env = environment()
    results: list[dict[str, object]] = []
    for name, fn, memory in cases(args.quick):
        results.append({"name": name, **measure(fn, args.repeats, memory)})
        print(f"{name}: {_fmt(float(results[-1]['best_s']))}", file=sys.stderr)  # type: ignore[arg-type]
    table = render(results, env, args.repeats)
    print(table)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        payload = {"environment": env, "quick": args.quick, "repeats": args.repeats,
                   "results": results}
        (args.out / "benchmarks.json").write_text(json.dumps(payload, indent=2) + "\n",
                                                  encoding="utf-8")
        (args.out / "benchmarks.md").write_text(table + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
