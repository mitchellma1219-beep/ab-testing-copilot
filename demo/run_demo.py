#!/usr/bin/env python3
"""Generate the demo assets: sample reports, an experiment plan and standalone HTML charts.

    python demo/run_demo.py                  # writes into demo/output/
    python demo/run_demo.py --out some/dir   # or anywhere else

Everything is computed from seeded synthetic data, so a second run writes the same files.
The charts open offline: ``charts/plotly.min.js`` (the MIT-licensed Plotly.js bundle shipped
inside the ``plotly`` Python package) is written next to them once and shared by all pages.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

try:
    import ab_testing_copilot  # noqa: F401
except ModuleNotFoundError:  # running from a repository checkout without installation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from plotly.offline import get_plotlyjs

from ab_testing_copilot import charts, design
from ab_testing_copilot import sequential as seq
from ab_testing_copilot import simulation as sim
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
)
from ab_testing_copilot.plan import GuardrailPlan, PlanRequest, build_plan, render_plan
from ab_testing_copilot.report import render_markdown, render_simulations
from ab_testing_copilot.synthetic import SCENARIOS, make_experiment, make_scenario, make_sessions
from ab_testing_copilot.units import aggregate_to_units

CONVERTED = MetricSpec(column="converted", type="binary")
LOAD = GuardrailSpec(column="page_load_ms", type="continuous", higher_is_better=False)
PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ margin: 0; background: #f9f9f7; color: #0b0b0b;
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; line-height: 1.5; }}
  main {{ max-width: 960px; margin: 0 auto; padding: 32px 20px 56px; }}
  h1 {{ font-size: 24px; margin: 0 0 8px; }}
  p {{ color: #52514e; margin: 0 0 16px; max-width: 72ch; }}
  a {{ color: #1c5cab; }}
  .card {{ background: #fcfcfb; border: 1px solid rgba(11, 11, 11, 0.10); border-radius: 8px;
           padding: 8px; margin: 16px 0; }}
  details {{ margin: 12px 0; }}
  summary {{ cursor: pointer; color: #52514e; }}
  .scroll {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; font-size: 13px; margin-top: 8px;
           font-variant-numeric: tabular-nums; }}
  th, td {{ border-bottom: 1px solid #e1e0d9; padding: 4px 12px 4px 0; text-align: left;
            white-space: nowrap; }}
  th {{ color: #52514e; font-weight: 600; }}
  li {{ margin: 6px 0; }}
</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.5g}"
    return html.escape(str(value))


def _table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{html.escape(str(k))}</th>" for k in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{_cell(v)}</td>" for v in r.values()) + "</tr>"
                   for r in rows)
    return ("<details><summary>View as table</summary><div class=\"scroll\"><table><thead><tr>"
            f"{head}</tr></thead><tbody>{body}</tbody></table></div></details>")


def chart_page(slug: str, title: str, intro: str, fig: object,
               rows: list[dict[str, object]]) -> str:
    """A standalone page: heading, what the chart shows, the chart, and its table twin."""
    div = fig.to_html(full_html=False, include_plotlyjs=False, div_id=f"chart-{slug}",
                      config={"displaylogo": False, "responsive": True})
    body = (f"<p><a href=\"index.html\">All charts</a></p>\n<h1>{html.escape(title)}</h1>\n"
            f"<p>{html.escape(intro)}</p>\n<script src=\"plotly.min.js\"></script>\n"
            f"<div class=\"card\">{div}</div>\n{_table(rows)}")
    return PAGE.format(title=html.escape(title), body=body)


def build(out: Path) -> list[Path]:
    """Write every asset under ``out`` and return the files written."""
    charts_dir = out / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save(path: Path, text: str) -> None:
        path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        written.append(path)

    pages: list[tuple[str, str, str]] = []

    def page(slug: str, title: str, intro: str, fig: object,
             rows: list[dict[str, object]]) -> None:
        save(charts_dir / f"{slug}.html", chart_page(slug, title, intro, fig, rows))
        pages.append((slug, title, intro))

    # 1. A clean win: effects, guardrail, novelty check, exploratory segments, A/A check.
    clean = analyze_experiment(make_scenario("clean_win"), ExperimentConfig(
        primary=CONVERTED, guardrails=[LOAD], unit_col="user_id", absolute_mde=0.015,
        date_col="exposure_date", segment_col="segment", aa_relabels=1000))
    save(out / "report_clean_win.md", render_markdown(clean, "Decision report: clean win"))
    save(out / "report_clean_win.json",
         json.dumps(json.loads(clean.model_dump_json()), indent=2, allow_nan=False))
    page("effects", "Effects with intervals",
         SCENARIOS["clean_win"].truth + " The recommendation is Ship.",
         charts.effects_figure(clean), charts.effects_rows(clean))
    page("aa_check", "A/A check on the same data",
         "Units are re-labelled at random 1,000 times and the test is repeated. Every "
         "rejection is a false positive, so the bars should be flat and about 5% of the "
         "p-values should fall below 0.05.",
         charts.aa_figure(clean.aa_check),
         [{"bin": f"[{i / 10:.1f}, {(i + 1) / 10:.1f})", "count": c}
          for i, c in enumerate(clean.aa_check.p_value_histogram)])

    # 2. A sample ratio mismatch: a significant-looking loss that must not be trusted.
    srm = analyze_experiment(make_scenario("sample_ratio_mismatch"), ExperimentConfig(
        primary=CONVERTED, guardrails=[LOAD], unit_col="user_id"))
    save(out / "report_sample_ratio_mismatch.md",
         render_markdown(srm, "Decision report: sample ratio mismatch"))

    # 3. Novelty decay: Ship, but with weak evidence and a warning.
    fading = analyze_experiment(make_scenario("novelty_decay"), ExperimentConfig(
        primary=CONVERTED, unit_col="user_id", date_col="exposure_date"))
    save(out / "report_novelty_decay.md",
         render_markdown(fading, "Decision report: novelty decay"))
    page("novelty", "Treatment effect over time", SCENARIOS["novelty_decay"].truth
         + " The check reports the trend as a warning with its evidence, never as proof.",
         charts.novelty_figure(fading.novelty), charts.novelty_rows(fading.novelty))

    # 4. Exploratory segments.
    mixed = analyze_experiment(make_scenario("segment_heterogeneity"), ExperimentConfig(
        primary=CONVERTED, unit_col="user_id", segment_col="segment"))
    save(out / "report_segment_heterogeneity.md",
         render_markdown(mixed, "Decision report: segment heterogeneity"))
    page("segments", "Exploratory: effect by segment", SCENARIOS["segment_heterogeneity"].truth
         + " Segment results are hypotheses for a follow-up test and never change the "
         "recommendation.", charts.segments_figure(mixed.segments),
         charts.segment_rows(mixed.segments))

    # 5. A pre-registered sequential design at an interim look and at the look that stops.
    data = make_experiment(n=8000, lift=0.03)
    for look in (2, 3):
        design_k = seq.SequentialDesign(method="obrien-fleming", planned_looks=4,
                                        current_look=look, planned_sample_size=8000)
        report = analyze_experiment(data.iloc[: 2000 * look], ExperimentConfig(
            primary=CONVERTED, unit_col="user_id", sequential=design_k))
        save(out / f"report_sequential_look{look}.md",
             render_markdown(report, f"Decision report: sequential design, look {look} of 4"))
        if look == 2:
            page("sequential_boundaries", "Sequential stopping boundaries",
                 "Four planned looks with O'Brien-Fleming-type alpha spending. At look 2 the "
                 f"z statistic is {report.primary.statistic:.2f}: a fixed 5% test would call "
                 f"it significant, the boundary ({report.sequential.critical_value:.2f}) does "
                 "not, and the experiment continues.",
                 charts.boundaries_figure(report.sequential.plan, report.primary.statistic,
                                          look), charts.boundary_rows(report.sequential.plan))

    # 6. Rows finer than the randomised unit: aggregate, then a delta-method ratio metric.
    sessions = make_sessions(n_users=6000, ctr_lift=0.02, seed=4)
    users = aggregate_to_units(sessions, "user_id", {"clicks": "sum", "impressions": "sum"})
    ratio = analyze_experiment(users, ExperimentConfig(
        primary=MetricSpec(column="clicks", type="ratio", denominator="impressions"),
        unit_col="user_id", absolute_mde=0.02, aa_relabels=1000))
    save(out / "report_ratio_metric.md",
         render_markdown(ratio, "Decision report: click-through rate as a ratio metric"))

    # 7. An experiment plan.
    plan = build_plan(PlanRequest(
        hypothesis="A shorter checkout form raises purchase conversion because fewer users "
                   "abandon at the address step.",
        metric="converted", metric_type="binary", higher_is_better=True, baseline=0.10,
        mde=0.01, mde_is_relative=False, alpha=0.05, power=0.8, treatment_share=0.5,
        unit="user_id", daily_units=3000, traffic_share=0.5,
        guardrails=[GuardrailPlan(name="page_load_ms", type="continuous",
                                  higher_is_better=False, margin=0.02)],
        looks=4, sequential_method="obrien-fleming"))
    save(out / "experiment_plan.md", render_plan(plan))

    # 8. Design and simulation charts.
    size = design.sample_size_for_proportions(0.10, 0.01)
    points = design.power_curve("binary", 0.01, 2 * size.n_control, baseline=0.10)
    page("power_curve", "Power curve",
         "Baseline conversion 10%, minimum detectable effect 1 percentage point, alpha 0.05: "
         f"80% power needs {size.n_control:,} users per arm.",
         charts.power_curve_figure(points, 0.8, size.n_control),
         [{"units in control arm": n, "power": p} for n, p in points])
    p_values, lo, hi = sim.simulate_p_values("binary", 5000, 5000, 0.0, 0.10, n_sims=4000,
                                             seed=1)
    counts = [int(v) for v in np.histogram(p_values, bins=20, range=(0, 1))[0]]
    share = float((p_values < 0.05).mean())
    page("p_values", "P-values when there is no effect",
         "4,000 simulated experiments with a true effect of zero (conversion 10%, 5,000 users "
         f"per arm). The histogram is flat and {share:.1%} of the p-values are below 0.05.",
         charts.p_value_histogram(counts, 0.05),
         [{"bin": f"[{i / 20:.2f}, {(i + 1) / 20:.2f})", "count": c}
          for i, c in enumerate(counts)])
    covered = int(((lo[:100] <= 0) & (hi[:100] >= 0)).sum())
    page("coverage", "Simulated confidence intervals",
         f"The first 100 of those simulated experiments: {covered} of the 95% intervals "
         "contain the true effect of zero.",
         charts.coverage_figure(lo, hi, 0.0),
         [{"experiment": i + 1, "CI low": float(a), "CI high": float(b)}
          for i, (a, b) in enumerate(zip(lo[:100], hi[:100], strict=True))])
    rules = [
        ("Fixed 5% test repeated at every look", sim.simulate_peeking(1000, 5, 0.05, False,
                                                                     4000, 2)),
        ("Bonferroni (alpha / looks)", sim.simulate_peeking(1000, 5, 0.05, True, 4000, 2)),
        ("O'Brien-Fleming-type boundary", sim.simulate_sequential("obrien-fleming", 5,
                                                                 n_sims=4000, seed=2)),
        ("Pocock-type boundary", sim.simulate_sequential("pocock", 5, n_sims=4000, seed=2)),
    ]
    page("peeking", "False-positive rate by analysis rule",
         "No true effect, five equally spaced looks, 4,000 simulated experiments per rule. "
         "Repeating a fixed test inflates false positives; the spending boundaries keep them "
         "at alpha.",
         charts.rates_figure([n for n, _ in rules], [r.estimate for _, r in rules],
                             [r.mc_standard_error for _, r in rules], 0.05),
         [{"rule": n, "false-positive rate": r.estimate,
           "MC standard error": r.mc_standard_error} for n, r in rules])
    save(out / "validation_suite.md",
         "# Monte Carlo validation suite\n\n`abcopilot simulate --n-sims 5000 --seed 0`\n\n"
         + render_simulations(sim.run_validation_suite(5000, 0)))

    items = "\n".join(f"<li><a href=\"{slug}.html\">{html.escape(title)}</a><br>"
                      f"{html.escape(intro)}</li>" for slug, title, intro in pages)
    save(charts_dir / "index.html", PAGE.format(
        title="A/B Testing Copilot: demo charts",
        body="<h1>A/B Testing Copilot: demo charts</h1>\n<p>Generated by "
             "<code>python demo/run_demo.py</code> from seeded synthetic data. Each page "
             f"works offline and has a table view of its numbers.</p>\n<ul>\n{items}\n</ul>"))
    save(charts_dir / "plotly.min.js", get_plotlyjs())
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "output")
    args = ap.parse_args(argv)
    for path in build(args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
