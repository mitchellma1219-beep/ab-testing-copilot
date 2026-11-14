"""Chart builders for the dashboard and the demo. Pure functions: data in, Plotly figure out.

No Streamlit, no I/O, no global state. Every chart has a table twin (the ``*_rows`` functions)
so no value is readable only by hovering. Colours follow a small fixed system: series identity
uses at most two validated categorical hues (blue, then orange), context marks are grey, text
always wears text colours, and each chart has a single value axis.

Requires Plotly (``pip install "ab-testing-copilot[ui]"``).
"""

from __future__ import annotations

import html
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import plotly.graph_objects as go

from ab_testing_copilot.decision import confidence_level
from ab_testing_copilot.models import (
    AAResult,
    DecisionReport,
    EffectEstimate,
    NoveltyResult,
    SegmentAnalysis,
    SequentialBoundaries,
)

Mode = Literal["light", "dark"]
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
_Z_AXIS_CAP = 6.5


@dataclass(frozen=True)
class Theme:
    """Colour roles for one mode. Categorical order is fixed: series[0] blue, series[1] orange."""

    surface: str
    ink: str
    ink_secondary: str
    muted: str
    grid: str
    axis: str
    series: tuple[str, str]
    context: str


THEMES: dict[str, Theme] = {
    "light": Theme(surface="#fcfcfb", ink="#0b0b0b", ink_secondary="#52514e", muted="#898781",
                   grid="#e1e0d9", axis="#c3c2b7", series=("#2a78d6", "#eb6834"),
                   context="#898781"),
    "dark": Theme(surface="#1a1a19", ink="#f0efec", ink_secondary="#c3c2b7", muted="#898781",
                  grid="#2c2c2a", axis="#383835", series=("#3987e5", "#d95926"),
                  context="#898781"),
}


def _theme(mode: str) -> Theme:
    if mode not in THEMES:
        raise ValueError(f"mode must be 'light' or 'dark', got {mode!r}")
    return THEMES[mode]


def _label(text: object, limit: int = 60) -> str:
    """Text from the data, made safe for Plotly (which renders a subset of HTML in labels)."""
    raw = " ".join(str(text).split())
    if len(raw) > limit:
        raw = raw[: limit - 1] + "…"
    return html.escape(raw, quote=False)


def _figure(title: str, subtitle: str, mode: str, height: int = 380,
            hovermode: str = "closest", legend: bool = False) -> go.Figure:
    t = _theme(mode)
    fig = go.Figure()
    axis: dict[str, Any] = dict(
        gridcolor=t.grid, gridwidth=1, griddash="solid", zeroline=True, zerolinecolor=t.axis,
        zerolinewidth=1, linecolor=t.axis, linewidth=1, ticks="", automargin=True,
        tickfont=dict(color=t.muted, size=12),
        title=dict(font=dict(color=t.ink_secondary, size=12), standoff=12),
    )
    fig.update_layout(
        title=dict(text=title, x=0.02, xanchor="left", xref="container", y=0.96, yanchor="top",
                   font=dict(color=t.ink, size=16),
                   subtitle=dict(text=subtitle, font=dict(color=t.ink_secondary, size=12))),
        font=dict(family=FONT, color=t.ink_secondary, size=13),
        paper_bgcolor=t.surface, plot_bgcolor=t.surface, height=height,
        margin=dict(l=16, r=24, t=96 if legend else 76, b=16),
        hovermode=hovermode, showlegend=legend,
        hoverlabel=dict(bgcolor=t.surface, bordercolor=t.axis,
                        font=dict(color=t.ink, family=FONT, size=12)),
        legend=dict(orientation="h", x=0, xanchor="left", y=1.02, yanchor="bottom",
                    font=dict(color=t.ink_secondary, size=12), bgcolor="rgba(0,0,0,0)"),
        xaxis={**axis, "zeroline": False}, yaxis=axis, barcornerradius=4,
    )
    if hovermode == "x unified":  # crosshair: the reader aims at an x position, not at a line
        fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1,
                         spikecolor=t.axis, spikedash="solid", spikesnap="data")
    return fig


def _note(fig: go.Figure, text: str, mode: str, x: float | str, y: float | str, *,
          xref: str = "x",
          yref: str = "y", xanchor: str = "left", yanchor: str = "bottom",
          primary: bool = False) -> None:
    t = _theme(mode)
    fig.add_annotation(text=text, x=x, y=y, xref=xref, yref=yref, showarrow=False,
                       xanchor=xanchor, yanchor=yanchor, xshift=6 if xanchor == "left" else -6,
                       font=dict(color=t.ink if primary else t.muted, size=12))


def empty_figure(message: str, mode: Mode = "light", title: str = "") -> go.Figure:
    """Placeholder when there is nothing to plot; says why instead of drawing an empty frame."""
    fig = _figure(title, "", mode, height=220)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.add_annotation(text=_label(message, 200), x=0.5, y=0.5, xref="paper", yref="paper",
                       showarrow=False, font=dict(color=_theme(mode).ink_secondary, size=13))
    return fig


def power_curve_figure(
    points: Sequence[tuple[float, float]], target_power: float, required_n: int, *,
    comparison: Sequence[tuple[float, float]] | None = None,
    labels: tuple[str, str] = ("Fixed horizon", "Group sequential"), mode: Mode = "light",
) -> go.Figure:
    """Power against sample size per arm, with the target and the required size marked."""
    if len(points) < 2:
        raise ValueError("a power curve needs at least 2 points")
    t = _theme(mode)
    two = comparison is not None
    fig = _figure("Power curve", "Chance of detecting the minimum detectable effect, by "
                  "sample size", mode, hovermode="x unified", legend=two)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines", name=labels[0], line=dict(color=t.series[0], width=2),
        hovertemplate="%{y:.1%}<extra>" + _label(labels[0]) + "</extra>"))
    if comparison is not None:
        fig.add_trace(go.Scatter(
            x=[p[0] for p in comparison], y=[p[1] for p in comparison], mode="lines",
            name=labels[1], line=dict(color=t.series[1], width=2),
            hovertemplate="%{y:.1%}<extra>" + _label(labels[1]) + "</extra>"))
    fig.add_shape(type="line", xref="paper", x0=0, x1=1, y0=target_power, y1=target_power,
                  line=dict(color=t.axis, width=1))
    _note(fig, f"target {target_power:.0%}", mode, 1, target_power, xref="paper",
          xanchor="right")
    reached = float(np.interp(required_n, xs, ys))
    fig.add_trace(go.Scatter(
        x=[required_n], y=[reached], mode="markers", showlegend=False, hoverinfo="skip",
        marker=dict(color=t.series[0], size=10, line=dict(color=t.surface, width=2))))
    _note(fig, f"{required_n:,} per arm", mode, required_n, reached, yanchor="top",
          primary=True)
    fig.update_xaxes(title_text="Units in the control arm", tickformat=",d", rangemode="tozero")
    fig.update_yaxes(title_text="Power", tickformat=".0%", range=[0, 1.04])
    return fig


def _relative(e: EffectEstimate) -> tuple[float, float, float] | None:
    if e.relative_effect is None or e.rel_ci_low is None or e.rel_ci_high is None:
        return None
    if not all(math.isfinite(v) for v in (e.relative_effect, e.rel_ci_low, e.rel_ci_high)):
        return None
    return e.relative_effect, e.rel_ci_low, e.rel_ci_high


def effects_rows(report: DecisionReport) -> list[dict[str, object]]:
    """Table twin of :func:`effects_figure`: one row per metric."""
    rows: list[dict[str, object]] = []
    items = [("primary", report.primary, None), *[
        ("guardrail", g.estimate, g) for g in report.guardrails]]
    for role, e, guard in items:
        rows.append({
            "metric": e.metric, "role": role, "control": e.control_value,
            "treatment": e.treatment_value, "absolute effect": e.absolute_effect,
            "CI low": e.ci_low, "CI high": e.ci_high, "relative effect": e.relative_effect,
            "relative CI low": e.rel_ci_low, "relative CI high": e.rel_ci_high,
            "p-value": e.p_value, "confidence level": confidence_level(e.alpha),
            "n control": e.n_control, "n treatment": e.n_treatment,
            "guardrail status": guard.status if guard is not None else "",
        })
    return rows


def effects_figure(report: DecisionReport, mode: Mode = "light") -> go.Figure:
    """Relative effect and interval for the primary metric and every guardrail.

    Relative effects share one axis even when the metrics have different units. A metric
    whose relative effect is undefined (control value <= 0) is listed in the table only.
    """
    t = _theme(mode)
    items = [(f"{_label(report.primary.metric)}  (primary)", report.primary)]
    items += [(f"{_label(g.estimate.metric)}  (guardrail: {g.status})", g.estimate)
              for g in report.guardrails]
    usable = [(name, e, rel) for name, e in items if (rel := _relative(e)) is not None]
    title = "Effects with intervals"
    if not usable:
        return empty_figure("Relative effects are undefined here (control value at or below "
                            "zero). See the table for absolute effects.", mode, title)
    level = confidence_level(report.primary.alpha)
    fig = _figure(title, f"Relative change against control, {level} interval. Zero means no "
                  "change.", mode, height=150 + 56 * len(usable))
    names = [n for n, _, _ in usable]
    est = [r[0] for _, _, r in usable]
    fig.add_trace(go.Scatter(
        x=est, y=names, mode="markers", name="Effect",
        marker=dict(color=t.series[0], size=11, line=dict(color=t.surface, width=2)),
        error_x=dict(type="data", symmetric=False, thickness=2, width=0, color=t.series[0],
                     array=[r[2] - r[0] for _, _, r in usable],
                     arrayminus=[r[0] - r[1] for _, _, r in usable]),
        customdata=[[r[1], r[2], e.p_value] for _, e, r in usable],
        hovertemplate=("<b>%{x:+.2%}</b>  [%{customdata[0]:+.2%}, %{customdata[1]:+.2%}]"
                       "<br>p = %{customdata[2]:.4g}<extra>%{y}</extra>")))
    lead = usable[0][2]
    _note(fig, f"{lead[0]:+.1%}  [{lead[1]:+.1%}, {lead[2]:+.1%}]", mode, lead[2], names[0],
          yanchor="middle", primary=True)
    fig.update_xaxes(title_text="Relative effect", tickformat="+.0%", zeroline=True,
                     zerolinecolor=t.muted, rangemode="tozero")
    fig.update_yaxes(autorange="reversed", showgrid=False, zeroline=False,
                     tickfont=dict(color=t.ink_secondary))
    return fig


def boundary_rows(bounds: SequentialBoundaries) -> list[dict[str, object]]:
    """Table twin of :func:`boundaries_figure`."""
    return [{"look": k, "information fraction": f, "critical value (abs z)": c,
             "nominal two-sided alpha": a, "cumulative alpha spent": s}
            for k, (f, c, a, s) in enumerate(zip(
                bounds.information_fractions, bounds.critical_values, bounds.nominal_alpha,
                bounds.cumulative_alpha, strict=True), 1)]


def boundaries_figure(
    bounds: SequentialBoundaries, observed_z: float | None = None,
    current_look: int | None = None, mode: Mode = "light",
) -> go.Figure:
    """Stopping boundaries of a group-sequential design and, optionally, the observed z."""
    t = _theme(mode)
    label = "O'Brien-Fleming-type" if bounds.method == "obrien-fleming" else "Pocock-type"
    shown = observed_z is not None and current_look is not None
    looks = list(range(1, len(bounds.critical_values) + 1))
    upper = [c if math.isfinite(c) else None for c in bounds.critical_values]
    lower = [-c if c is not None else None for c in upper]
    finite = [c for c in bounds.critical_values if math.isfinite(c)]
    top = min(_Z_AXIS_CAP, max([*finite, abs(observed_z or 0.0), 2.5]) * 1.12)
    beyond = any(c is None or c > top for c in upper)
    fig = _figure("Sequential stopping boundaries",
                  f"{label} alpha spending, two-sided alpha {bounds.alpha:g}. Stop only when "
                  "z leaves the band." + (" The earliest boundaries lie beyond the axis."
                                          if beyond else ""),
                  mode, hovermode="x unified", legend=shown)
    for i, values in enumerate((upper, lower)):
        fig.add_trace(go.Scatter(
            x=looks, y=values, mode="lines+markers", name="Stopping boundary",
            legendgroup="boundary", showlegend=i == 0, connectgaps=False,
            line=dict(color=t.series[0], width=2),
            marker=dict(color=t.series[0], size=8, line=dict(color=t.surface, width=2)),
            hovertemplate="%{y:+.3f}<extra>" + ("upper" if i == 0 else "lower")
                          + " boundary</extra>"))
    if shown and observed_z is not None and current_look is not None:
        fig.add_trace(go.Scatter(
            x=[current_look], y=[observed_z], mode="markers", name="Observed z at this look",
            marker=dict(color=t.series[1], size=12, symbol="diamond",
                        line=dict(color=t.surface, width=2)),
            hovertemplate="%{y:+.3f}<extra>observed z</extra>"))
        _note(fig, f"z = {observed_z:+.2f}", mode, current_look,
              max(-top, min(top, observed_z)), primary=True,
              yanchor="top" if observed_z >= 0 else "bottom")
    fig.update_xaxes(title_text="Look", tickmode="array", tickvals=looks,
                     ticktext=[f"{k}<br>{f:.0%}" for k, f in
                               zip(looks, bounds.information_fractions, strict=True)],
                     showgrid=False, range=[0.6, len(looks) + 0.6])
    fig.update_yaxes(title_text="z statistic", range=[-top, top], zerolinecolor=t.muted)
    return fig


def novelty_rows(novelty: NoveltyResult) -> list[dict[str, object]]:
    """Table twin of :func:`novelty_figure`."""
    return [{"period": p.label, "day": p.index, "n control": p.n_control,
             "n treatment": p.n_treatment, "effect": p.effect, "std error": p.std_error}
            for p in novelty.periods]


def novelty_figure(novelty: NoveltyResult, mode: Mode = "light") -> go.Figure:
    """Treatment effect per period with its fitted trend."""
    title = "Treatment effect over time"
    if not novelty.assessed or not novelty.periods or novelty.slope is None:
        return empty_figure(novelty.reason or "The novelty check was not assessed.", mode, title)
    t = _theme(mode)
    verdict = ("the effect shrinks towards zero: a warning, not proof" if novelty.decay_detected
               else "the effect grows over time" if novelty.growth_detected
               else "the effect changes sign over time" if novelty.reversal_detected
               else "no clear trend")
    fig = _figure(title, f"Effect per period with 95% intervals; {verdict}.", mode,
                  hovermode="x unified", legend=True)
    x = [p.index for p in novelty.periods]
    fig.add_trace(go.Scatter(
        x=x, y=[p.effect for p in novelty.periods], mode="markers", name="Effect in the period",
        marker=dict(color=t.series[0], size=9, line=dict(color=t.surface, width=2)),
        error_y=dict(type="data", array=[1.959964 * p.std_error for p in novelty.periods],
                     thickness=1.5, width=0, color=t.series[0]),
        customdata=[[_label(p.label), p.std_error, p.n_control + p.n_treatment]
                    for p in novelty.periods],
        hovertemplate=("<b>%{y:+.4f}</b>  (SE %{customdata[1]:.4f}, n = %{customdata[2]:,})"
                       "<extra>%{customdata[0]}</extra>")))
    fig.add_trace(go.Scatter(
        x=[x[0], x[-1]], y=[novelty.fitted_start, novelty.fitted_end], mode="lines",
        name="Fitted trend", line=dict(color=t.series[1], width=2),
        hovertemplate="%{y:+.4f}<extra>trend</extra>"))
    p_text = "p < 0.001" if (novelty.p_value or 0) < 0.001 else f"p = {novelty.p_value:.3f}"
    falling = novelty.slope < 0  # the corner the points move away from is the free one
    _note(fig, f"trend {novelty.slope:+.4f} per day ({p_text})", mode, 1,
          1 if falling else 0, xref="paper", yref="paper", xanchor="right",
          yanchor="top" if falling else "bottom", primary=True)
    step = max(1, len(x) // 7)
    fig.update_xaxes(title_text="Period (date of first exposure)", tickmode="array",
                     tickvals=x[::step],
                     ticktext=[_label(p.label) for p in novelty.periods[::step]], showgrid=False)
    fig.update_yaxes(title_text="Absolute effect", tickformat="+.3~f", zerolinecolor=t.muted,
                     rangemode="tozero")
    return fig


def segment_rows(segments: SegmentAnalysis) -> list[dict[str, object]]:
    """Table twin of :func:`segments_figure`, including the segments that were left out."""
    rows: list[dict[str, object]] = [{
        "segment": s.segment, "n control": s.estimate.n_control,
        "n treatment": s.estimate.n_treatment, "effect": s.estimate.absolute_effect,
        "simultaneous CI low": s.simultaneous_ci_low,
        "simultaneous CI high": s.simultaneous_ci_high, "p-value": s.estimate.p_value,
        "adjusted p-value": s.adjusted_p_value,
        "significant after correction": s.significant_after_correction, "note": "",
    } for s in segments.segments]
    rows += [{"segment": k.segment, "n control": k.n_control, "n treatment": k.n_treatment,
              "effect": None, "simultaneous CI low": None, "simultaneous CI high": None,
              "p-value": None, "adjusted p-value": None, "significant after correction": None,
              "note": f"not analysed: {k.reason}"} for k in segments.skipped]
    return rows


def segments_figure(segments: SegmentAnalysis, mode: Mode = "light") -> go.Figure:
    """Exploratory per-segment effects with simultaneous intervals."""
    title = "Exploratory: effect by segment"
    if not segments.segments:
        return empty_figure("No segment could be analysed.", mode, title)
    t = _theme(mode)
    level = confidence_level(segments.alpha)
    fig = _figure(title, f"Absolute effect with simultaneous {level} intervals. Hypotheses for "
                  "a follow-up test, not findings.", mode,
                  height=170 + 48 * len(segments.segments), legend=True)
    method = segments.correction.title()
    if segments.pooled_effect is not None:
        fig.add_trace(go.Scatter(
            x=[segments.pooled_effect] * 2,
            y=[_label(segments.segments[0].segment), _label(segments.segments[-1].segment)],
            mode="lines", name="Pooled effect", line=dict(color=t.context, width=1.5),
            hovertemplate="%{x:+.4f}<extra>pooled effect</extra>"))
    for flag, name, symbol in ((True, f"Significant after {method} correction", "circle"),
                               (False, "Not significant after correction", "circle-open")):
        part = [s for s in segments.segments if s.significant_after_correction is flag]
        fig.add_trace(go.Scatter(
            x=[s.estimate.absolute_effect for s in part],
            y=[_label(s.segment) for s in part], mode="markers", name=name,
            marker=dict(color=t.series[0], size=11, symbol=symbol,
                        line=dict(color=t.series[0] if not flag else t.surface, width=2)),
            error_x=dict(
                type="data", symmetric=False, thickness=2, width=0, color=t.series[0],
                array=[s.simultaneous_ci_high - s.estimate.absolute_effect for s in part],
                arrayminus=[s.estimate.absolute_effect - s.simultaneous_ci_low for s in part]),
            customdata=[[s.simultaneous_ci_low, s.simultaneous_ci_high, s.adjusted_p_value,
                         s.estimate.n_control + s.estimate.n_treatment] for s in part],
            hovertemplate=("<b>%{x:+.4f}</b>  [%{customdata[0]:+.4f}, %{customdata[1]:+.4f}]"
                           "<br>adjusted p = %{customdata[2]:.4g}, n = %{customdata[3]:,}"
                           "<extra>%{y}</extra>")))
    fig.update_xaxes(title_text="Absolute effect", tickformat="+.3~f", zeroline=True,
                     zerolinecolor=t.muted, rangemode="tozero")
    fig.update_yaxes(categoryorder="array",
                     categoryarray=[_label(s.segment) for s in segments.segments][::-1],
                     showgrid=False, zeroline=False, tickfont=dict(color=t.ink_secondary))
    return fig


def p_value_histogram(
    counts: Sequence[int], alpha: float = 0.05, mode: Mode = "light",
    title: str = "P-values across simulated experiments",
) -> go.Figure:
    """Histogram of p-values in equal bins on [0, 1]; flat when there is no effect.

    Bins that lie entirely below ``alpha`` (the rejections) carry the accent colour and the
    rest recede, so the share of rejections is what the eye lands on.
    """
    n_bins = len(counts)
    if n_bins < 2:
        raise ValueError("a histogram needs at least 2 bins")
    t = _theme(mode)
    total = int(sum(counts))
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    mids = (edges[:-1] + edges[1:]) / 2
    below = [bool(edges[i + 1] <= alpha + 1e-12) for i in range(n_bins)]
    split = any(below) and not all(below)
    fig = _figure(title, f"{total:,} p-values in {n_bins} equal bins; the line is the count "
                  "per bin expected when there is no effect.", mode, legend=split)
    groups = ([(True, f"p < {alpha:g} (significant)", t.series[0]),
               (False, f"p ≥ {alpha:g}", t.context)] if split
              else [(None, "p-values", t.series[0])])
    for flag, name, colour in groups:
        idx = [i for i in range(n_bins) if flag is None or below[i] is flag]
        fig.add_trace(go.Bar(
            x=[float(mids[i]) for i in idx], y=[int(counts[i]) for i in idx], name=name,
            width=(1.0 / n_bins) * 0.5, marker=dict(color=colour, line=dict(width=0)),
            customdata=[[float(edges[i]), float(edges[i + 1]),
                         counts[i] / total if total else 0.0] for i in idx],
            hovertemplate=("<b>%{y:,}</b>  (%{customdata[2]:.1%})<extra>p in "
                           "[%{customdata[0]:.2f}, %{customdata[1]:.2f})</extra>")))
    expected = total / n_bins
    fig.add_shape(type="line", xref="paper", x0=0, x1=1, y0=expected, y1=expected,
                  line=dict(color=t.muted, width=1))
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(title_text="p-value", range=[0, 1], showgrid=False, tickformat=".1f")
    fig.update_yaxes(title_text="Simulated experiments", rangemode="tozero", tickformat=",d")
    return fig


def aa_figure(result: AAResult, mode: Mode = "light") -> go.Figure:
    """P-values of the A/A re-labellings; flat when the analysis is calibrated on this data."""
    return p_value_histogram(
        result.p_value_histogram, result.alpha, mode,
        title=f"A/A check: p-values under random re-labelling ({result.verdict})")


def coverage_figure(
    ci_low: Sequence[float], ci_high: Sequence[float], truth: float, *, limit: int = 100,
    mode: Mode = "light",
) -> go.Figure:
    """The first ``limit`` simulated intervals; the ones that miss the truth stand out."""
    if len(ci_low) != len(ci_high) or len(ci_low) == 0:
        raise ValueError("ci_low and ci_high must be non-empty and of equal length")
    t = _theme(mode)
    lo = [float(v) for v in ci_low[:limit]]
    hi = [float(v) for v in ci_high[:limit]]
    hit = [a <= truth <= b for a, b in zip(lo, hi, strict=True)]
    fig = _figure("Simulated confidence intervals",
                  f"First {len(lo)} simulated experiments around a true effect of "
                  f"{truth:+.4g} (the line): {sum(hit)} intervals cover it, "
                  f"{len(lo) - sum(hit)} miss.", mode, legend=True)
    for flag, name, colour, width in ((True, "Covers the true effect", t.context, 1.5),
                                      (False, "Misses the true effect", t.series[0], 2.5)):
        xs: list[float | None] = []
        ys: list[float | None] = []
        for i, (a, b, h) in enumerate(zip(lo, hi, hit, strict=True), 1):
            if h is flag:
                xs += [i, i, None]
                ys += [a, b, None]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=name,
                                 line=dict(color=colour, width=width),
                                 hovertemplate="%{y:+.4f}<extra>experiment %{x}</extra>"))
    fig.add_shape(type="line", xref="paper", x0=0, x1=1, y0=truth, y1=truth,
                  line=dict(color=t.ink_secondary, width=1))
    fig.update_xaxes(title_text="Simulated experiment", showgrid=False, tickformat="d",
                     range=[0, len(lo) + 1])
    fig.update_yaxes(title_text="Interval for the effect", tickformat="+.3~f", zeroline=False)
    return fig


def rates_figure(
    labels: Sequence[str], rates: Sequence[float], standard_errors: Sequence[float],
    reference: float, *, reference_label: str = "alpha",
    title: str = "False-positive rate by analysis rule", mode: Mode = "light",
) -> go.Figure:
    """Horizontal bars for a handful of rates against one reference line (one hue, one axis)."""
    if not (len(labels) == len(rates) == len(standard_errors)) or not labels:
        raise ValueError("labels, rates and standard_errors must be non-empty, equal length")
    t = _theme(mode)
    fig = _figure(title, "Bars show the simulated rate; whiskers are 2 Monte Carlo standard "
                  f"errors; the line marks {_label(reference_label)} = {reference:.3g}.", mode,
                  height=150 + 52 * len(labels))
    names = [_label(v) for v in labels]
    fig.add_trace(go.Bar(
        x=list(rates), y=names, orientation="h", width=0.42,
        marker=dict(color=t.series[0], line=dict(width=0)),
        error_x=dict(type="data", array=[2 * s for s in standard_errors], thickness=1.5,
                     width=0, color=t.ink_secondary),
        hovertemplate="<b>%{x:.2%}</b><extra>%{y}</extra>"))
    fig.add_trace(go.Scatter(  # value labels sit beyond the whisker, never on top of it
        x=[r + 2 * s for r, s in zip(rates, standard_errors, strict=True)], y=names,
        mode="text", text=[f"  {r:.1%}" for r in rates], textposition="middle right",
        textfont=dict(color=t.ink, size=12), hoverinfo="skip", cliponaxis=False))
    fig.add_shape(type="line", yref="paper", y0=0, y1=1, x0=reference, x1=reference,
                  line=dict(color=t.muted, width=1))
    reach = max(r + 2 * s for r, s in zip(rates, standard_errors, strict=True))
    fig.update_xaxes(title_text="Share of simulated experiments declared significant",
                     tickformat=".0%", range=[0, max(reach * 1.22, reference * 2, 0.02)])
    fig.update_yaxes(autorange="reversed", showgrid=False, zeroline=False,
                     tickfont=dict(color=t.ink_secondary))
    return fig
