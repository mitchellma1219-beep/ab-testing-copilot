"""A/B Testing Copilot dashboard: a thin Streamlit UI over the ``ab_testing_copilot`` package.

Run it with::

    streamlit run app/streamlit_app.py

It works offline. The default data are built-in synthetic scenarios with a known ground truth;
a CSV can be uploaded instead. Every number on screen is computed by the package: this file
only collects inputs, calls library functions and lays out their results.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import ab_testing_copilot  # noqa: F401
except ModuleNotFoundError:  # running from a repository checkout without installation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
import streamlit as st
from pydantic import ValidationError

from ab_testing_copilot import __version__, charts, design
from ab_testing_copilot import sequential as seq
from ab_testing_copilot import simulation as sim
from ab_testing_copilot.decision import confidence_level
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
)
from ab_testing_copilot.models import DecisionReport
from ab_testing_copilot.report import render_markdown, safe_text
from ab_testing_copilot.synthetic import SCENARIOS, make_scenario

MAX_UPLOAD_ROWS = 2_000_000
MAX_UPLOAD_MB = 100
NONE = "(none)"
TABS = ["Experiment setup", "Power calculator", "Simulation", "Statistical results",
        "Diagnostic warnings", "Decision report", "Export"]
PLOT_CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
STATUS = {  # every status is an icon plus a word, never colour alone
    "ok": (":material/check_circle:", "OK"),
    "warning": (":material/warning:", "Warning"),
    "blocking": (":material/block:", "Blocking"),
    "not_assessed": (":material/help:", "Not assessed"),
}


def md(text: object) -> str:
    """Data-derived text made safe for Streamlit Markdown (which also reads $ as LaTeX)."""
    return safe_text(text).replace("$", "\\$")


def chart_mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # no theme outside a browser session (tests, scripts): use light
        return "light"


def show_chart(fig: object, rows: list[dict[str, object]] | None, key: str) -> None:
    """A chart with its table twin, so no value is readable only by hovering."""
    st.plotly_chart(fig, theme=None, config=PLOT_CONFIG, key=key)
    if rows:
        with st.expander("View as table"):
            st.dataframe(pd.DataFrame(rows), hide_index=True, key=f"{key}_table")


@st.cache_data(show_spinner=False)
def load_scenario(name: str, seed: int) -> pd.DataFrame:
    return make_scenario(name, seed)


@st.cache_data(show_spinner="Analysing the experiment...")
def run_analysis(df: pd.DataFrame, config_json: str) -> DecisionReport:
    return analyze_experiment(df, ExperimentConfig.model_validate_json(config_json))


@st.cache_data(show_spinner="Running simulations...")
def run_fixed_simulation(distribution: str, n: int, effect: float, baseline: float,
                         alpha: float, n_sims: int, seed: int) -> dict[str, object]:
    p, lo, hi = sim.simulate_p_values(distribution, n, n, effect, baseline, 1.0, alpha, n_sims,
                                      seed)
    if effect == 0:
        rate = sim.simulate_false_positive_rate(distribution, n, n, baseline, 1.0, alpha,
                                                n_sims, seed)
    else:
        rate = sim.simulate_power(effect, distribution, n, n, baseline, 1.0, alpha, n_sims,
                                  seed)
    cover = sim.simulate_coverage(effect, distribution, n, n, baseline, 1.0, alpha, n_sims,
                                  seed)
    return {"rate": rate, "coverage": cover, "ci_low": lo[:100], "ci_high": hi[:100],
            "histogram": [int(v) for v in np.histogram(p, bins=20, range=(0, 1))[0]]}


@st.cache_data(show_spinner="Running simulations...")
def run_looks_simulation(n: int, looks: int, alpha: float, n_sims: int, seed: int) -> list:
    return [
        ("Fixed test repeated at every look",
         sim.simulate_peeking(n, looks, alpha, False, n_sims, seed)),
        ("Bonferroni (alpha / looks)", sim.simulate_peeking(n, looks, alpha, True, n_sims, seed)),
        ("O'Brien-Fleming-type boundary",
         sim.simulate_sequential("obrien-fleming", looks, n, alpha=alpha, n_sims=n_sims,
                                 seed=seed)),
        ("Pocock-type boundary",
         sim.simulate_sequential("pocock", looks, n, alpha=alpha, n_sims=n_sims, seed=seed)),
    ]


def numeric_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
            and not pd.api.types.is_bool_dtype(df[c])]


def looks_binary(series: pd.Series) -> bool:
    return bool(series.dropna().isin([0, 1]).all())


def variant_labels(series: pd.Series) -> pd.Series:
    """Variant labels as text (0/1 or True/False columns included); missing stays missing."""
    return series.where(series.isna(), series.astype(str))


def sync_metric_type(df: pd.DataFrame) -> None:
    """When another primary metric is picked, set its type from the values it holds."""
    metric = st.session_state.get("metric")
    if metric in df.columns:
        st.session_state["metric_type"] = "binary" if looks_binary(df[metric]) else "continuous"


def pick(options: list[str], preferred: str, fallback: int = 0) -> int:
    return options.index(preferred) if preferred in options else min(fallback, len(options) - 1)


def sidebar() -> tuple[pd.DataFrame | None, str]:
    """Data source. Returns the table and a short description of where it came from."""
    with st.sidebar:
        st.header("A/B Testing Copilot")
        st.caption("Design, diagnose, analyse and decide on randomised experiments. "
                   "Prefers Inconclusive over a confident wrong answer.")
        source = st.radio("Data", ["Built-in scenario", "Upload a CSV"], key="source")
        if source == "Built-in scenario":
            name = st.selectbox("Scenario", list(SCENARIOS), key="scenario",
                                format_func=lambda k: SCENARIOS[k].title)
            seed = int(st.number_input("Random seed", 0, 10_000, 7, key="seed"))
            st.info(SCENARIOS[name].truth, icon=":material/science:")
            st.caption("Synthetic data generated on this machine. No network, no real users.")
            return load_scenario(name, seed), f"Built-in scenario: {SCENARIOS[name].title}"
        upload = st.file_uploader("CSV with one row per randomised unit", type=["csv"],
                                  key="upload", max_upload_size=MAX_UPLOAD_MB)
        st.caption("The file stays in this session's memory; nothing is written or sent.")
        if upload is None:
            return None, "No file uploaded"
        try:
            df = pd.read_csv(upload, nrows=MAX_UPLOAD_ROWS + 1)
        except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError,
                UnicodeDecodeError) as exc:
            st.error(f"Could not read the file: {md(exc)}")
            return None, "Unreadable file"
        if len(df) > MAX_UPLOAD_ROWS:
            st.error(f"The file has more than {MAX_UPLOAD_ROWS:,} rows.")
            return None, "File too large"
        return df, "Uploaded CSV"


def setup_tab(df: pd.DataFrame, origin: str) -> ExperimentConfig | None:
    """Collect the analysis configuration. Returns ``None`` when it is not valid yet."""
    st.subheader("Data")
    st.caption(origin)
    columns = [str(c) for c in df.columns]
    numeric = numeric_columns(df)
    if len(columns) < 2 or not numeric:
        st.error("The table needs a variant column and at least one numeric metric column.")
        return None
    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", f"{len(df):,}")
    c2.metric("Columns", f"{len(columns)}")
    variant_col = c3.selectbox("Variant column", columns, pick(columns, "variant"),
                               key="variant_col")
    labels = [str(v) for v in variant_labels(df[variant_col]).value_counts().index[:50]]
    if len(labels) < 2:
        st.error("The variant column needs at least two labels.")
        return None
    l1, l2 = st.columns(2)
    control = l1.selectbox("Control label", labels, pick(labels, "control"), key="control")
    treatment = l2.selectbox("Treatment label", labels, pick(labels, "treatment", 1),
                             key="treatment")
    with st.expander("Preview the first rows"):
        st.dataframe(df.head(50), hide_index=True, key="preview")

    st.subheader("Metrics")
    m1, m2, m3 = st.columns(3)
    metric = m1.selectbox("Primary metric", numeric, pick(numeric, "converted"), key="metric",
                          on_change=sync_metric_type, args=(df,))
    kinds = ["binary", "continuous"]
    kind = m2.selectbox("Metric type", kinds, 0 if looks_binary(df[metric]) else 1,
                        key="metric_type")
    better = m3.selectbox("Direction", ["Higher is better", "Lower is better"], key="direction")
    others = [c for c in numeric if c != metric]
    guards = st.multiselect("Guardrail metrics", others,
                            [c for c in ("page_load_ms",) if c in others], key="guardrails")
    g1, g2 = st.columns(2)
    lower = g1.multiselect("Guardrails where lower is better", guards,
                           [c for c in guards if c == "page_load_ms"], key="guardrails_lower")
    margin = g2.number_input("Tolerated relative harm (guardrail margin)", 0.0, 1.0, 0.02,
                             0.005, format="%.3f", key="margin")

    st.subheader("Design")
    d1, d2, d3 = st.columns(3)
    optional = [NONE, *columns]
    unit = d1.selectbox("Randomisation unit column", optional, pick(optional, "user_id"),
                        key="unit_col")
    covariate = d2.selectbox("Pre-experiment covariate (CUPED)", [NONE, *others], key="covariate")
    alpha = d3.number_input("Alpha (two-sided)", 0.001, 0.5, 0.05, 0.005, format="%.3f",
                            key="alpha")
    e1, e2, e3 = st.columns(3)
    share = e1.number_input("Planned treatment share", 0.01, 0.99, 0.5, 0.05, key="share")
    use_mde = e2.checkbox("Declare the MDE from the design", key="use_mde")
    mde = e3.number_input("Absolute MDE", 0.0001, 1e9, 0.015, format="%.4f", key="mde",
                          disabled=not use_mde)

    st.subheader("Looks at the data")
    looks_mode = st.radio(
        "How many times were the results analysed?",
        ["One planned analysis", "Several looks without a plan",
         "Pre-registered sequential design"], key="looks_mode", horizontal=True)
    n_looks, sequential = 1, None
    if looks_mode == "Several looks without a plan":
        n_looks = int(st.number_input("Number of looks so far", 2, 100, 3, key="n_looks"))
        st.caption("A Bonferroni threshold (alpha divided by the number of looks) is applied.")
    elif looks_mode == "Pre-registered sequential design":
        s1, s2, s3, s4 = st.columns(4)
        method = s1.selectbox("Alpha spending", ["obrien-fleming", "pocock"], key="seq_method",
                              format_func=lambda k: seq.METHOD_LABELS[k])
        planned = int(s2.number_input("Planned looks", 2, 20, 4, key="seq_planned"))
        current = int(s3.number_input("This is look", 1, 20, min(2, planned), key="seq_current"))
        planned_n = int(s4.number_input("Planned total sample (0 = not declared)", 0, 10**9, 0,
                                        key="seq_planned_n"))
        sequential = {"method": method, "planned_looks": planned, "current_look": current,
                      "planned_sample_size": planned_n or None}

    st.subheader("Optional checks")
    o1, o2, o3 = st.columns(3)
    date_col = o1.selectbox("Exposure date column (novelty check)", optional,
                            pick(optional, "exposure_date"), key="date_col")
    segment = o2.selectbox("Segment column (exploratory)", optional,
                           pick(optional, "segment"), key="segment_col")
    relabels = o3.selectbox("A/A check: random re-labellings", [0, 300, 1000], key="aa_relabels",
                            format_func=lambda n: "Off" if n == 0 else f"{n:,}")
    try:
        return ExperimentConfig(
            variant_col=variant_col, control_label=control, treatment_label=treatment,
            primary=MetricSpec(column=metric, type=kind,
                               higher_is_better=better == "Higher is better"),
            guardrails=[GuardrailSpec(
                column=g, type="binary" if looks_binary(df[g]) else "continuous",
                higher_is_better=g not in lower, margin=margin) for g in guards],
            unit_col=None if unit == NONE else unit,
            covariate_col=None if covariate == NONE else covariate,
            expected_treatment_share=share, alpha=alpha,
            absolute_mde=mde if use_mde else None, n_looks=n_looks, sequential=sequential,
            date_col=None if date_col == NONE else date_col,
            segment_col=None if segment == NONE else segment, aa_relabels=relabels,
        )
    except ValidationError as exc:
        st.error("The configuration is not valid: "
                 + md("; ".join(e["msg"] for e in exc.errors())))
        return None


def power_tab(mode: str) -> None:
    st.subheader("Sample size and power")
    st.caption("Fixed-horizon formulas (normal approximation). All inputs are yours: nothing "
               "is filled in from the data.")
    a, b, c, d = st.columns(4)
    kind = a.selectbox("Metric type", ["binary", "continuous"], key="pw_type")
    baseline = b.number_input("Baseline rate" if kind == "binary" else "Baseline mean",
                              value=0.10, format="%.4f", key="pw_baseline")
    std = c.number_input("Standard deviation", 0.0001, 1e9, 1.0, format="%.4f", key="pw_std",
                         disabled=kind == "binary")
    mde = d.number_input("Absolute MDE", 0.00001, 1e9, 0.02, format="%.4f", key="pw_mde")
    e, f, g, h = st.columns(4)
    alpha = e.number_input("Alpha", 0.001, 0.5, 0.05, 0.005, format="%.3f", key="pw_alpha")
    power = f.number_input("Power", 0.5, 0.999, 0.8, 0.05, format="%.3f", key="pw_power")
    ratio = g.number_input("Allocation ratio (treatment / control)", 0.05, 20.0, 1.0, 0.25,
                           key="pw_ratio")
    daily = h.number_input("Eligible units per day", 1.0, 1e9, 1500.0, key="pw_daily")
    i, j, _, _ = st.columns(4)
    method = i.selectbox("Interim looks", ["none", "obrien-fleming", "pocock"], key="pw_seq",
                         format_func=lambda k: "None (fixed horizon)" if k == "none"
                         else seq.METHOD_LABELS[k])
    looks = int(j.number_input("Planned looks", 2, 20, 4, key="pw_looks",
                               disabled=method == "none"))
    try:
        if kind == "binary":
            size = design.sample_size_for_proportions(baseline, mde, alpha, power, ratio)
        else:
            size = design.sample_size_for_means(std, mde, alpha, power, ratio, baseline)
        n_total = size.n_total
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Control arm", f"{size.n_control:,}")
        k2.metric("Treatment arm", f"{size.n_treatment:,}")
        if method != "none":
            bounds = seq.sequential_boundaries(looks, alpha, method)
            factor = seq.inflation_factor(bounds, power)
            n_total = int(np.ceil(size.n_control * factor)) + int(
                np.ceil(np.ceil(size.n_control * factor) * ratio))
            stop = seq.expected_information(bounds.critical_values, bounds.information_fractions,
                                            seq.required_drift(bounds, power))
            k3.metric("Maximum total with interim looks", f"{n_total:,}",
                      f"x{factor:.4f} vs fixed horizon", delta_color="off", delta_arrow="off")
            k4.metric("Days at the stated traffic",
                      f"{design.duration_days(n_total, daily):,}",
                      f"stops at {stop:.0%} of the maximum on average if the MDE is real",
                      delta_color="off", delta_arrow="off")
        else:
            k3.metric("Total", f"{n_total:,}")
            k4.metric("Days at the stated traffic", f"{design.duration_days(n_total, daily):,}")
        points = design.power_curve(kind, mde, 2 * size.n_control, baseline=baseline,
                                    std_dev=std, alpha=alpha, allocation_ratio=ratio)
        show_chart(charts.power_curve_figure(points, power, size.n_control, mode=mode),
                   [{"units in control arm": n, "power": p} for n, p in points], "power_curve")
        if method != "none":
            show_chart(charts.boundaries_figure(bounds, mode=mode), charts.boundary_rows(bounds),
                       "power_boundaries")
        with st.expander("Assumptions"):
            for text in (size.assumptions if method == "none"
                         else seq.sequential_assumptions(size.assumptions)):
                st.markdown(f"- {md(text)}")
    except ValueError as exc:
        st.error(md(exc))


def simulation_tab(mode: str) -> None:
    st.subheader("Interactive Monte Carlo")
    st.caption("Simulate thousands of experiments with a known truth and see how the "
               "procedures behave. Seeded: the same inputs give the same result.")
    kind = st.radio("What to simulate", ["A fixed-horizon test", "Repeated looks at growing data"],
                    key="sim_kind", horizontal=True)
    with st.form("simulation"):
        a, b, c, d = st.columns(4)
        n = int(a.number_input("Units per arm", 20, 50_000, 1000, key="sim_n"))
        alpha = b.number_input("Alpha", 0.001, 0.5, 0.05, 0.005, format="%.3f", key="sim_alpha")
        n_sims = int(c.number_input("Simulated experiments", 200, 10_000, 2000, 200,
                                    key="sim_n_sims"))
        seed = int(d.number_input("Seed", 0, 10_000, 0, key="sim_seed"))
        if kind == "A fixed-horizon test":
            e, f, g, _ = st.columns(4)
            distribution = e.selectbox("Outcome distribution", ["normal", "binary", "lognormal"],
                                       key="sim_dist")
            effect = f.number_input("True effect (0 = no effect)", -0.5, 0.5, 0.0, 0.01,
                                    format="%.4f", key="sim_effect")
            baseline = g.number_input("Baseline rate (binary only)", 0.01, 0.99, 0.10,
                                      key="sim_baseline")
            looks = 1
        else:
            e, _, _, _ = st.columns(4)
            looks = int(e.number_input("Looks", 2, 20, 5, key="sim_looks"))
            distribution, effect, baseline = "normal", 0.0, 0.1
        submitted = st.form_submit_button("Run simulation", type="primary")
    if submitted:
        st.session_state["sim_request"] = (kind, distribution, n, effect, baseline, alpha,
                                           n_sims, seed, looks)
    request = st.session_state.get("sim_request")
    if request is None:
        st.info("Choose the settings and run the simulation.", icon=":material/play_circle:")
        return
    kind, distribution, n, effect, baseline, alpha, n_sims, seed, looks = request
    try:
        if kind == "A fixed-horizon test":
            out = run_fixed_simulation(distribution, n, effect, baseline, alpha, n_sims, seed)
            rate, cover = out["rate"], out["coverage"]
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("False-positive rate" if effect == 0 else "Power", f"{rate.estimate:.1%}")
            k2.metric("Expected from theory", f"{rate.expected:.1%}")
            k3.metric("Interval coverage", f"{cover.estimate:.1%}",
                      f"nominal {cover.expected:.1%}", delta_color="off", delta_arrow="off")
            k4.metric("Monte Carlo standard error", f"{rate.mc_standard_error:.2%}")
            hist = out["histogram"]
            show_chart(charts.p_value_histogram(hist, alpha, mode),
                       [{"bin": f"[{i / 20:.2f}, {(i + 1) / 20:.2f})", "count": c}
                        for i, c in enumerate(hist)], "sim_histogram")
            show_chart(charts.coverage_figure(out["ci_low"], out["ci_high"], effect, mode=mode),
                       [{"experiment": i + 1, "CI low": float(lo), "CI high": float(hi)}
                        for i, (lo, hi) in enumerate(zip(out["ci_low"], out["ci_high"],
                                                         strict=True))], "sim_coverage")
        else:
            results = run_looks_simulation(n, looks, alpha, n_sims, seed)
            show_chart(
                charts.rates_figure([name for name, _ in results],
                                    [r.estimate for _, r in results],
                                    [r.mc_standard_error for _, r in results], alpha, mode=mode),
                [{"rule": name, "false-positive rate": r.estimate,
                  "MC standard error": r.mc_standard_error} for name, r in results],
                "sim_rates")
            st.caption(f"No true effect, {looks} equally spaced looks, {n_sims:,} simulated "
                       "experiments. Repeating a fixed test inflates false positives; the "
                       "spending boundaries keep them at alpha.")
    except ValueError as exc:
        st.error(md(exc))


def results_tab(report: DecisionReport, mode: str) -> None:
    p = report.primary
    st.subheader("Primary metric")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Absolute effect", f"{p.absolute_effect:+.4g}",
              f"[{p.ci_low:+.4g}, {p.ci_high:+.4g}]", delta_color="off", delta_arrow="off")
    k2.metric("Relative effect", "n/a" if p.relative_effect is None
              else f"{p.relative_effect:+.2%}",
              None if p.rel_ci_low is None else f"[{p.rel_ci_low:+.2%}, {p.rel_ci_high:+.2%}]",
              delta_color="off", delta_arrow="off")
    k3.metric("p-value", f"{p.p_value:.4g}")
    k4.metric("Units (control / treatment)", f"{p.n_control:,} / {p.n_treatment:,}")
    st.caption(f"Method: {md(p.method)}. Intervals are at the "
               f"{confidence_level(report.effective_alpha)} level.")
    show_chart(charts.effects_figure(report, mode), charts.effects_rows(report), "effects")
    look = report.sequential
    if look is not None:
        st.subheader("Sequential design")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Look", f"{look.current_look} of {look.planned_looks}")
        s2.metric("Critical value (abs z)", f"{look.critical_value:.4f}")
        s3.metric("Observed z", f"{p.statistic:+.3f}")
        s4.metric("Alpha spent", f"{look.cumulative_alpha:.4f}", f"of {look.overall_alpha:g}",
                  delta_color="off", delta_arrow="off")
        show_chart(charts.boundaries_figure(look.plan, p.statistic, look.current_look, mode),
                   charts.boundary_rows(look.plan), "boundaries")
    if report.segments is not None:
        st.subheader("Segments")
        st.warning(report.segments.label, icon=":material/explore:")
        show_chart(charts.segments_figure(report.segments, mode),
                   charts.segment_rows(report.segments), "segments")
        st.caption(md(report.segments.message))


def diagnostics_tab(report: DecisionReport, mode: str) -> None:
    def state(d: object) -> str:
        if not d.assessed:
            return "not_assessed"
        return "ok" if d.passed else d.severity

    states = [state(d) for d in report.diagnostics]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Blocking", states.count("blocking"))
    k2.metric("Warnings", states.count("warning"))
    k3.metric("Passed", states.count("ok") + states.count("info"))
    k4.metric("Not assessed", states.count("not_assessed"))
    order = {"blocking": 0, "warning": 1, "not_assessed": 2, "ok": 3, "info": 3}
    for d, s in sorted(zip(report.diagnostics, states, strict=True),
                       key=lambda pair: order[pair[1]]):
        icon, word = STATUS["ok" if s == "info" else s]
        with st.container(border=True):
            st.markdown(f"{icon} **{word}** &nbsp; `{md(d.name)}`")
            st.markdown(md(d.message))
    if report.novelty is not None:
        st.subheader("Novelty check")
        show_chart(charts.novelty_figure(report.novelty, mode),
                   charts.novelty_rows(report.novelty), "novelty")
    if report.aa_check is not None:
        st.subheader("A/A check")
        show_chart(charts.aa_figure(report.aa_check, mode),
                   [{"bin": f"[{i / 10:.1f}, {(i + 1) / 10:.1f})", "count": c}
                    for i, c in enumerate(report.aa_check.p_value_histogram)], "aa")


def decision_tab(report: DecisionReport) -> None:
    banner = {"Ship": (st.success, ":material/check_circle:"),
              "Do not ship": (st.error, ":material/cancel:"),
              "Inconclusive": (st.warning, ":material/help:")}[report.decision.value]
    banner[0](f"**Recommendation: {report.decision.value}**", icon=banner[1])
    k1, k2, k3 = st.columns(3)
    k1.metric("Evidence quality", report.evidence_quality)
    k2.metric("Confidence level", confidence_level(report.effective_alpha))
    k3.metric("Guardrails cleared",
              f"{sum(g.status == 'pass' for g in report.guardrails)} of {len(report.guardrails)}")
    st.subheader("Why")
    for reason in report.reasons:
        st.markdown(f"- {md(reason)}")
    if report.guardrails:
        st.subheader("Guardrails")
        marks = {"pass": STATUS["ok"][0], "fail": STATUS["blocking"][0],
                 "uncertain": STATUS["not_assessed"][0]}
        for g in report.guardrails:
            st.markdown(f"{marks[g.status]} **{g.status.capitalize()}** &nbsp; {md(g.message)}")
        if report.evidence_quality == "invalid":
            st.caption("The experiment failed validity checks, so these guardrail results "
                       "are no more trustworthy than the primary effect.")
    flagged = [d for d in report.diagnostics if d.assessed and not d.passed]
    if flagged:
        st.subheader("Checks that did not pass")
        for d in flagged:
            icon, word = STATUS[d.severity]
            st.markdown(f"{icon} **{word}** &nbsp; `{md(d.name)}` &nbsp; {md(d.message)}")
    with st.expander("Assumptions behind this recommendation"):
        for text in report.assumptions:
            st.markdown(f"- {md(text)}")


def export_tab(report: DecisionReport, origin: str) -> None:
    st.subheader("Download the report")
    markdown = render_markdown(report, f"Decision report ({origin})")
    payload = json.dumps(json.loads(report.model_dump_json()), indent=2, allow_nan=False)
    c1, c2 = st.columns(2)
    c1.download_button("Download Markdown", markdown, "decision_report.md", "text/markdown",
                       key="download_md", type="primary", icon=":material/download:")
    c2.download_button("Download JSON", payload, "decision_report.json", "application/json",
                       key="download_json", icon=":material/download:")
    with st.container(border=True):
        st.markdown(markdown.replace("$", "\\$"))
    with st.expander("Raw Markdown"):
        st.code(markdown, language=None)
    with st.expander("Raw JSON"):
        st.code(payload, language="json")


def main() -> None:
    st.set_page_config(page_title="A/B Testing Copilot", layout="wide")
    df, origin = sidebar()
    st.title("A/B Testing Copilot")
    st.caption(f"Version {__version__}. Statistics computed by the ab_testing_copilot "
               "package; this page is only its user interface.")
    mode = chart_mode()
    setup, power, simulate, results, diagnostics, decision, export = st.tabs(TABS)
    config = None
    with setup:
        if df is None:
            st.info("Upload a CSV in the sidebar, or switch to a built-in scenario.",
                    icon=":material/upload_file:")
        else:
            config = setup_tab(df, origin)
    with power:
        power_tab(mode)
    with simulate:
        simulation_tab(mode)
    report = None
    if df is not None and config is not None:
        try:
            labelled = df.assign(**{config.variant_col: variant_labels(df[config.variant_col])})
            report = run_analysis(labelled, config.model_dump_json())
        except ValueError as exc:
            with setup:
                st.error(f"The analysis could not run: {md(exc)}")
    for tab, render in ((results, lambda r: results_tab(r, mode)),
                        (diagnostics, lambda r: diagnostics_tab(r, mode)),
                        (decision, decision_tab),
                        (export, lambda r: export_tab(r, origin))):
        with tab:
            if report is None:
                st.info("Complete the experiment setup first.", icon=":material/tune:")
            else:
                render(report)


main()
