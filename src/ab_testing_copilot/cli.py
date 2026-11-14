"""Command-line interface.

``abcopilot plan | design | sequential | analyze | aa | srm | simulate``
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from ab_testing_copilot import design
from ab_testing_copilot import sequential as seq
from ab_testing_copilot.aa import aa_check
from ab_testing_copilot.diagnostics import srm_check
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
)
from ab_testing_copilot.plan import (
    GuardrailPlan,
    PlanRequest,
    build_plan,
    plan_gaps,
    render_plan,
)
from ab_testing_copilot.report import render_boundaries, render_markdown, render_simulations
from ab_testing_copilot.simulation import run_validation_suite
from ab_testing_copilot.units import aggregate_to_units, parse_aggregations

MAX_ROWS = int(os.environ.get("ABCOPILOT_MAX_ROWS", "5000000"))
METHODS = ["obrien-fleming", "pocock"]


def _guardrail(text: str) -> GuardrailSpec:
    """Parse ``column:type[:higher|lower[:margin]]``; a ratio column is ``num/den``."""
    parts = text.split(":")
    if len(parts) < 2 or len(parts) > 4:
        raise argparse.ArgumentTypeError("guardrail must be column:type[:higher|lower[:margin]]")
    direction = parts[2] if len(parts) > 2 else "higher"
    if direction not in ("higher", "lower"):
        raise argparse.ArgumentTypeError("guardrail direction must be 'higher' or 'lower'")
    column, denominator = parts[0], None
    if parts[1] == "ratio":
        column, _, denominator = parts[0].partition("/")
    try:
        return GuardrailSpec(column=column, type=parts[1], denominator=denominator or None,
                             higher_is_better=direction == "higher",
                             margin=float(parts[3]) if len(parts) > 3 else 0.02)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _fractions(text: str) -> list[float]:
    try:
        return [float(v) for v in text.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "information fractions must be comma-separated numbers, e.g. 0.25,0.5,1") from exc


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
    d.add_argument("--sequential", choices=METHODS, help="alpha-spending method for --looks")
    d.add_argument("--looks", type=int, default=1, help="planned looks (with --sequential)")

    a = sub.add_parser("analyze", help="analyse a row-level CSV")
    a.add_argument("csv", type=Path)
    a.add_argument("--variant-col", default="variant")
    a.add_argument("--control", default="control")
    a.add_argument("--treatment", default="treatment")
    a.add_argument("--metric", required=True)
    a.add_argument("--metric-type", choices=["binary", "continuous", "ratio"], required=True)
    a.add_argument("--denominator", help="denominator column of a ratio metric")
    a.add_argument("--lower-is-better", action="store_true")
    a.add_argument("--guardrail", type=_guardrail, action="append", default=[])
    a.add_argument("--unit-col")
    a.add_argument("--aggregate", help="rows are finer than the unit: collapse them first, "
                   "e.g. clicks=sum,impressions=sum,segment=unique (adds n_rows)")
    a.add_argument("--covariate", help="pre-experiment covariate for CUPED")
    a.add_argument("--expected-share", type=float, default=0.5)
    a.add_argument("--alpha", type=float, default=0.05)
    a.add_argument("--mde", type=float, help="absolute MDE from the design")
    a.add_argument("--looks", type=int, default=1,
                   help="times the results were inspected without a plan (Bonferroni)")
    a.add_argument("--sequential", choices=METHODS,
                   help="pre-registered alpha-spending method (needs --planned-looks, --look)")
    a.add_argument("--planned-looks", type=int)
    a.add_argument("--look", type=int, help="which planned look this analysis is")
    a.add_argument("--planned-n", type=int, help="pre-registered maximum total sample size")
    a.add_argument("--info-fractions", type=_fractions,
                   help="planned information fractions, e.g. 0.25,0.5,0.75,1")
    a.add_argument("--date-col", help="exposure date column for the novelty check")
    a.add_argument("--date-bin-days", type=int, default=1)
    a.add_argument("--segment-col", help="segment column (exploratory analysis)")
    a.add_argument("--segment-correction", default="holm",
                   choices=["holm", "bonferroni", "benjamini-hochberg"])
    a.add_argument("--aa-relabels", type=int, default=0,
                   help="run an A/A check with this many random re-labellings (0 = off)")
    a.add_argument("--seed", type=int, default=0)
    a.add_argument("--format", choices=["markdown", "json"], default="markdown")
    a.add_argument("--out", type=Path)

    q = sub.add_parser("sequential", help="group-sequential boundaries (Lan-DeMets)")
    q.add_argument("--method", choices=METHODS, required=True)
    q.add_argument("--looks", type=int, help="number of equally spaced looks")
    q.add_argument("--info-fractions", type=_fractions,
                   help="information fractions instead of --looks, e.g. 0.3,0.6,1")
    q.add_argument("--alpha", type=float, default=0.05)
    q.add_argument("--power", type=float, default=0.8, help="power for the inflation factor")
    q.add_argument("--format", choices=["markdown", "json"], default="markdown")

    c = sub.add_parser("aa", help="A/A check: false-positive rate under random re-labelling")
    c.add_argument("csv", type=Path)
    c.add_argument("--metric", required=True)
    c.add_argument("--metric-type", choices=["binary", "continuous", "ratio"], required=True)
    c.add_argument("--denominator")
    c.add_argument("--unit-col", help="randomised unit; labels are re-drawn per unit")
    c.add_argument("--treatment-share", type=float, default=0.5)
    c.add_argument("--relabels", type=int, default=1000)
    c.add_argument("--alpha", type=float, default=0.05)
    c.add_argument("--seed", type=int, default=0)

    s = sub.add_parser("srm", help="sample ratio mismatch check")
    s.add_argument("n_control", type=int)
    s.add_argument("n_treatment", type=int)
    s.add_argument("--expected-share", type=float, default=0.5)

    m = sub.add_parser("simulate", help="Monte Carlo validation suite")
    m.add_argument("--n-sims", type=int, default=5000)
    m.add_argument("--seed", type=int, default=0)
    m.add_argument("--format", choices=["markdown", "json"], default="markdown")

    g = sub.add_parser(
        "plan", help="experiment plan for pre-registration; refuses to guess missing inputs")
    g.add_argument("--hypothesis")
    g.add_argument("--metric")
    g.add_argument("--metric-type", choices=["binary", "continuous"])
    g.add_argument("--direction", choices=["higher", "lower"], help="which way is better")
    g.add_argument("--baseline", type=float)
    g.add_argument("--std-dev", type=float)
    g.add_argument("--mde", type=float, help="smallest effect worth detecting (positive)")
    g.add_argument("--mde-scale", choices=["absolute", "relative"],
                   help="whether --mde is in the metric's units or a share of the baseline")
    g.add_argument("--alpha", type=float)
    g.add_argument("--power", type=float)
    g.add_argument("--treatment-share", type=float)
    g.add_argument("--unit", help="randomisation unit, e.g. user_id")
    g.add_argument("--daily-units", type=float, help="new eligible units per day")
    g.add_argument("--traffic-share", type=float, help="share of eligible units enrolled")
    g.add_argument("--guardrail", action="append", default=[],
                   help="name:type:higher|lower:margin (all four parts)")
    g.add_argument("--no-guardrails", metavar="REASON",
                   help="state why no guardrail metric applies")
    g.add_argument("--looks", type=int, help="number of planned analyses (1 = fixed horizon)")
    g.add_argument("--sequential", choices=METHODS, help="alpha spending for --looks > 1")
    g.add_argument("--format", choices=["markdown", "json"], default="markdown")
    g.add_argument("--out", type=Path)
    return p


def _dumps(payload: object) -> str:
    """Strict JSON: infinities (a look that cannot stop) become null."""
    def clean(v: object) -> object:
        if isinstance(v, float) and not math.isfinite(v):
            return None
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, list | tuple):
            return [clean(x) for x in v]
        return v

    return json.dumps(clean(payload), indent=2, allow_nan=False)


def _design(a: argparse.Namespace) -> str:
    if a.baseline is None and (a.metric_type == "binary" or a.relative):
        raise ValueError("--baseline is required for binary metrics and relative MDEs")
    if (a.looks > 1) != (a.sequential is not None):
        raise ValueError("use --sequential together with --looks greater than 1")
    mde = a.mde * a.baseline if a.relative else a.mde
    if a.metric_type == "binary":
        res = design.sample_size_for_proportions(a.baseline, mde, a.alpha, a.power, a.ratio)
    else:
        if a.std_dev is None:
            raise ValueError("--std-dev is required for continuous metrics")
        res = design.sample_size_for_means(a.std_dev, mde, a.alpha, a.power, a.ratio, a.baseline)
    out = res.model_dump()
    n_total = res.n_total
    if a.sequential:
        bounds = seq.sequential_boundaries(a.looks, a.alpha, a.sequential)
        factor = seq.inflation_factor(bounds, a.power)
        n_c = math.ceil(res.n_control * factor)
        n_t = math.ceil(n_c * a.ratio)
        n_total = n_c + n_t
        out["sequential"] = {
            "method": a.sequential, "looks": a.looks, "inflation_factor": factor,
            "n_control_max": n_c, "n_treatment_max": n_t, "n_total_max": n_total,
            "critical_values": bounds.critical_values, "nominal_alpha": bounds.nominal_alpha,
        }
        out["assumptions"] = seq.sequential_assumptions(out["assumptions"])
    if a.daily_units:
        out["duration_days"] = design.duration_days(n_total, a.daily_units, a.traffic_share)
        out["assumptions"].append(
            f"Constant traffic of {a.daily_units:g} eligible units/day with "
            f"{a.traffic_share:.0%} enrolled; run whole weeks to cover weekly seasonality.")
    return _dumps(out)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise ValueError(f"file not found: {path}")
    if path.suffix.lower() != ".csv":
        raise ValueError("only .csv input is supported")
    df = pd.read_csv(path, nrows=MAX_ROWS + 1)
    if len(df) > MAX_ROWS:
        raise ValueError(f"input exceeds ABCOPILOT_MAX_ROWS={MAX_ROWS}")
    return df


def _sequential_design(a: argparse.Namespace) -> seq.SequentialDesign | None:
    given = [a.planned_looks is not None, a.look is not None]
    if a.sequential is None:
        if any(given) or a.planned_n is not None or a.info_fractions is not None:
            raise ValueError("--planned-looks, --look, --planned-n and --info-fractions need "
                             "--sequential")
        return None
    if not all(given):
        raise ValueError("--sequential needs both --planned-looks and --look")
    return seq.SequentialDesign(
        method=a.sequential, planned_looks=a.planned_looks, current_look=a.look,
        information_fractions=a.info_fractions, planned_sample_size=a.planned_n)


def _analyze(a: argparse.Namespace) -> str:
    df = _read_csv(a.csv)
    if a.aggregate:
        if not a.unit_col:
            raise ValueError("--aggregate needs --unit-col")
        df = aggregate_to_units(df, a.unit_col, parse_aggregations(a.aggregate), a.variant_col)
    cfg = ExperimentConfig(
        variant_col=a.variant_col, control_label=a.control, treatment_label=a.treatment,
        primary=MetricSpec(column=a.metric, type=a.metric_type, denominator=a.denominator,
                           higher_is_better=not a.lower_is_better),
        guardrails=a.guardrail, unit_col=a.unit_col, covariate_col=a.covariate,
        expected_treatment_share=a.expected_share, alpha=a.alpha, absolute_mde=a.mde,
        n_looks=a.looks, sequential=_sequential_design(a), date_col=a.date_col,
        date_bin_days=a.date_bin_days, segment_col=a.segment_col,
        segment_correction=a.segment_correction, aa_relabels=a.aa_relabels, seed=a.seed,
    )
    report = analyze_experiment(df, cfg)
    text = (_dumps(report.model_dump(mode="json")) if a.format == "json"
            else render_markdown(report, f"Decision report: {a.csv.name}"))
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    return text


def _sequential(a: argparse.Namespace) -> str:
    if (a.looks is None) == (a.info_fractions is None):
        raise ValueError("give either --looks or --info-fractions")
    bounds = seq.sequential_boundaries(a.looks, a.alpha, a.method, a.info_fractions)
    factor = seq.inflation_factor(bounds, a.power)
    drift = seq.required_drift(bounds, a.power)
    stop_h1 = seq.expected_information(bounds.critical_values, bounds.information_fractions,
                                       drift)
    stop_h0 = seq.expected_information(bounds.critical_values, bounds.information_fractions,
                                       0.0)
    if a.format == "json":
        return _dumps({**bounds.model_dump(), "power": a.power, "inflation_factor": factor,
                       "expected_stop_fraction_no_effect": stop_h0,
                       "expected_stop_fraction_at_design_effect": stop_h1})
    return "\n".join([
        f"{seq.METHOD_LABELS[a.method]} alpha spending, two-sided alpha = {a.alpha:g}", "",
        render_boundaries(bounds), "",
        f"Maximum sample size: {factor:.4f} x the fixed-horizon size for power {a.power:g}.",
        f"Expected stopping point: {stop_h1:.1%} of the maximum if the design effect is real, "
        f"{stop_h0:.1%} if there is no effect.", "",
        "Assumptions:", *[f"- {x}" for x in bounds.assumptions]])


def _aa(a: argparse.Namespace) -> tuple[str, int]:
    df = _read_csv(a.csv)
    res = aa_check(df, a.metric, a.metric_type, denominator=a.denominator, unit_col=a.unit_col,
                   treatment_share=a.treatment_share, n_relabels=a.relabels, alpha=a.alpha,
                   seed=a.seed)
    return res.model_dump_json(indent=2), 4 if res.verdict == "inflated" else 0


def _plan_guardrail(text: str) -> GuardrailPlan:
    parts = text.split(":")
    if len(parts) != 4 or parts[2] not in ("higher", "lower"):
        raise ValueError(
            f"guardrail '{text}' must state all four parts: name:type:higher|lower:margin")
    try:
        margin = float(parts[3])
    except ValueError as exc:
        raise ValueError(f"guardrail '{text}': the margin must be a number") from exc
    return GuardrailPlan(name=parts[0], type=parts[1], higher_is_better=parts[2] == "higher",
                         margin=margin)


def _plan(a: argparse.Namespace) -> str:
    values = {
        "hypothesis": a.hypothesis, "metric": a.metric, "metric_type": a.metric_type,
        "direction": a.direction, "baseline": a.baseline, "std_dev": a.std_dev, "mde": a.mde,
        "mde_scale": a.mde_scale, "alpha": a.alpha, "power": a.power,
        "treatment_share": a.treatment_share,
        "unit": a.unit, "daily_units": a.daily_units, "traffic_share": a.traffic_share,
        "guardrails": a.guardrail, "no_guardrails_reason": a.no_guardrails, "looks": a.looks,
        "sequential_method": a.sequential,
    }
    gaps = plan_gaps(values)
    if gaps:
        raise ValueError(
            "the plan is incomplete, and missing inputs are never guessed. Please supply:\n"
            + "\n".join(f"  --{g}" for g in gaps))
    request = PlanRequest(
        hypothesis=a.hypothesis, metric=a.metric, metric_type=a.metric_type,
        higher_is_better=a.direction == "higher", baseline=a.baseline, std_dev=a.std_dev,
        mde=a.mde, mde_is_relative=a.mde_scale == "relative", alpha=a.alpha, power=a.power,
        treatment_share=a.treatment_share, unit=a.unit, daily_units=a.daily_units,
        traffic_share=a.traffic_share, guardrails=[_plan_guardrail(g) for g in a.guardrail],
        no_guardrails_reason=a.no_guardrails, looks=a.looks, sequential_method=a.sequential,
    )
    plan = build_plan(request)
    text = _dumps(plan.model_dump(mode="json")) if a.format == "json" else render_plan(plan)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    return text


def _validation_message(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'input'}: {e['msg']}" for e in exc.errors())


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
        elif args.command == "sequential":
            print(_sequential(args))
        elif args.command == "plan":
            print(_plan(args))
        elif args.command == "aa":
            text, code = _aa(args)
            print(text)
            return code
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
    except ValidationError as e:
        print(f"error: {_validation_message(e)}", file=sys.stderr)
        return 1
    except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
