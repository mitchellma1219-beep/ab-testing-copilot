"""Command-line interface: ``abcopilot design | analyze | srm | simulate``."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from ab_testing_copilot import design
from ab_testing_copilot.diagnostics import srm_check
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
)
from ab_testing_copilot.report import render_markdown, render_simulations
from ab_testing_copilot.simulation import run_validation_suite

MAX_ROWS = int(os.environ.get("ABCOPILOT_MAX_ROWS", "5000000"))


def _guardrail(text: str) -> GuardrailSpec:
    """Parse ``column:type[:higher|lower[:margin]]``."""
    parts = text.split(":")
    if len(parts) < 2 or len(parts) > 4:
        raise argparse.ArgumentTypeError("guardrail must be column:type[:higher|lower[:margin]]")
    direction = parts[2] if len(parts) > 2 else "higher"
    if direction not in ("higher", "lower"):
        raise argparse.ArgumentTypeError("guardrail direction must be 'higher' or 'lower'")
    try:
        return GuardrailSpec(column=parts[0], type=parts[1],
                             higher_is_better=direction == "higher",
                             margin=float(parts[3]) if len(parts) > 3 else 0.02)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="abcopilot", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("design", help="sample size and duration")
    d.add_argument("--metric-type", choices=["binary", "continuous"], default="binary")
    d.add_argument("--baseline", type=float, help="baseline rate (binary) or mean (continuous)")
    d.add_argument("--std-dev", type=float, help="standard deviation (continuous)")
    d.add_argument("--mde", type=float, required=True, help="minimum detectable effect")
    d.add_argument("--relative", action="store_true", help="interpret --mde as relative lift")
    d.add_argument("--alpha", type=float, default=0.05)
    d.add_argument("--power", type=float, default=0.8)
    d.add_argument("--ratio", type=float, default=1.0, help="n_treatment / n_control")
    d.add_argument("--daily-units", type=float, help="eligible units per day")
    d.add_argument("--traffic-share", type=float, default=1.0)

    a = sub.add_parser("analyze", help="analyse a row-level CSV")
    a.add_argument("csv", type=Path)
    a.add_argument("--variant-col", default="variant")
    a.add_argument("--control", default="control")
    a.add_argument("--treatment", default="treatment")
    a.add_argument("--metric", required=True)
    a.add_argument("--metric-type", choices=["binary", "continuous"], required=True)
    a.add_argument("--lower-is-better", action="store_true")
    a.add_argument("--guardrail", type=_guardrail, action="append", default=[])
    a.add_argument("--unit-col")
    a.add_argument("--covariate", help="pre-experiment covariate for CUPED")
    a.add_argument("--expected-share", type=float, default=0.5)
    a.add_argument("--alpha", type=float, default=0.05)
    a.add_argument("--mde", type=float, help="absolute MDE from the design")
    a.add_argument("--looks", type=int, default=1, help="times the results were inspected")
    a.add_argument("--format", choices=["markdown", "json"], default="markdown")
    a.add_argument("--out", type=Path)

    s = sub.add_parser("srm", help="sample ratio mismatch check")
    s.add_argument("n_control", type=int)
    s.add_argument("n_treatment", type=int)
    s.add_argument("--expected-share", type=float, default=0.5)

    m = sub.add_parser("simulate", help="Monte Carlo validation suite")
    m.add_argument("--n-sims", type=int, default=5000)
    m.add_argument("--seed", type=int, default=0)
    m.add_argument("--format", choices=["markdown", "json"], default="markdown")
    return p


def _design(a: argparse.Namespace) -> str:
    if a.baseline is None and (a.metric_type == "binary" or a.relative):
        raise ValueError("--baseline is required for binary metrics and relative MDEs")
    mde = a.mde * a.baseline if a.relative else a.mde
    if a.metric_type == "binary":
        res = design.sample_size_for_proportions(a.baseline, mde, a.alpha, a.power, a.ratio)
    else:
        if a.std_dev is None:
            raise ValueError("--std-dev is required for continuous metrics")
        res = design.sample_size_for_means(a.std_dev, mde, a.alpha, a.power, a.ratio, a.baseline)
    out = res.model_dump()
    if a.daily_units:
        out["duration_days"] = design.duration_days(res.n_total, a.daily_units, a.traffic_share)
        out["assumptions"].append(
            f"Constant traffic of {a.daily_units:g} eligible units/day with "
            f"{a.traffic_share:.0%} enrolled; run whole weeks to cover weekly seasonality.")
    return json.dumps(out, indent=2)


def _analyze(a: argparse.Namespace) -> str:
    if not a.csv.is_file():
        raise ValueError(f"file not found: {a.csv}")
    if a.csv.suffix.lower() != ".csv":
        raise ValueError("only .csv input is supported")
    df = pd.read_csv(a.csv, nrows=MAX_ROWS + 1)
    if len(df) > MAX_ROWS:
        raise ValueError(f"input exceeds ABCOPILOT_MAX_ROWS={MAX_ROWS}")
    cfg = ExperimentConfig(
        variant_col=a.variant_col, control_label=a.control, treatment_label=a.treatment,
        primary=MetricSpec(column=a.metric, type=a.metric_type,
                           higher_is_better=not a.lower_is_better),
        guardrails=a.guardrail, unit_col=a.unit_col, covariate_col=a.covariate,
        expected_treatment_share=a.expected_share, alpha=a.alpha, absolute_mde=a.mde,
        n_looks=a.looks,
    )
    report = analyze_experiment(df, cfg)
    text = (report.model_dump_json(indent=2) if a.format == "json"
            else render_markdown(report, f"Decision report: {a.csv.name}"))
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    return text


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("ABCOPILOT_LOG_LEVEL", "WARNING"), stream=sys.stderr,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
    args = _parser().parse_args(argv)
    try:
        if args.command == "design":
            print(_design(args))
        elif args.command == "analyze":
            print(_analyze(args))
        elif args.command == "srm":
            d = srm_check(args.n_control, args.n_treatment, args.expected_share)
            print(d.model_dump_json(indent=2))
            return 0 if d.passed else 2
        else:
            results = run_validation_suite(args.n_sims, args.seed)
            if args.format == "json":
                print(json.dumps([r.model_dump() for r in results], indent=2))
            else:
                print(render_simulations(results))
            return 0 if all(r.passed is not False for r in results) else 3
    except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
