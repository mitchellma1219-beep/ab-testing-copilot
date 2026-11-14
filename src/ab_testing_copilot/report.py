"""Markdown rendering of decision reports, boundary tables and simulation results."""

from __future__ import annotations

import math
import re

from ab_testing_copilot.decision import confidence_level
from ab_testing_copilot.models import (
    DecisionReport,
    EffectEstimate,
    SequentialBoundaries,
    SimulationResult,
)

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_METHOD_LABELS = {"obrien-fleming": "O'Brien-Fleming-type", "pocock": "Pocock-type"}


def safe_text(text: object) -> str:
    """Neutralise text that came from the data (column names, labels) for use in Markdown.

    Control characters and line breaks become spaces, and the characters that open HTML tags,
    links, images, code spans or table cells are escaped, so a hostile column name cannot
    inject markup into a rendered report.
    """
    out = _CONTROL.sub(" ", str(text))
    for ch in ("\\", "`", "<", "|"):
        out = out.replace(ch, "\\" + ch)
    return out.replace("](", "]\\(").replace("![", "!\\[")


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.2%}"


def _num(v: float) -> str:
    return "inf" if math.isinf(v) else f"{v:.4f}"


def _effect_row(e: EffectEstimate) -> str:
    rel = (f"{_pct(e.relative_effect)} [{_pct(e.rel_ci_low)}, {_pct(e.rel_ci_high)}]"
           if e.relative_effect is not None else "n/a")
    return (f"| {safe_text(e.metric)} | {e.control_value:.5g} | {e.treatment_value:.5g} | "
            f"{e.absolute_effect:+.5g} [{e.ci_low:+.5g}, {e.ci_high:+.5g}] | {rel} | "
            f"{e.p_value:.4g} | {e.n_control:,} / {e.n_treatment:,} |")


def render_boundaries(b: SequentialBoundaries, current_look: int | None = None) -> str:
    """Table of a group-sequential design: one row per planned look."""
    lines = ["| Look | Information fraction | Critical value (abs z) | Nominal two-sided alpha "
             "| Cumulative alpha spent |", "|---|---|---|---|---|"]
    for k, (t, c, a, s) in enumerate(zip(b.information_fractions, b.critical_values,
                                         b.nominal_alpha, b.cumulative_alpha, strict=True), 1):
        mark = " (this look)" if current_look == k else ""
        lines.append(f"| {k}{mark} | {t:.3f} | {_num(c)} | {a:.3g} | {s:.3g} |")
    return "\n".join(lines)


def render_markdown(report: DecisionReport, title: str = "Experiment decision report") -> str:
    """Human-readable report. Contains only quantities computed from the data."""
    p = report.primary
    lines = [
        f"# {safe_text(title)}", "",
        f"**Recommendation: {report.decision.value}**  ",
        f"Evidence quality: **{report.evidence_quality}**  ",
        f"Confidence level for the primary metric: {confidence_level(report.effective_alpha)}",
        "", "## Why", "", *[f"- {safe_text(r)}" for r in report.reasons], "",
        "## Effects", "",
        "| Metric | Control | Treatment | Absolute effect [CI] | Relative effect [CI] | p "
        "| n (C / T) |",
        "|---|---|---|---|---|---|---|",
        _effect_row(p), *[_effect_row(g.estimate) for g in report.guardrails], "",
        f"Primary method: {p.method}.", "",
    ]
    if report.guardrails:
        lines += ["## Guardrails", "",
                  *[f"- **{g.status.upper()}** — {safe_text(g.message)}"
                    for g in report.guardrails], ""]
    seq = report.sequential
    if seq is not None:
        lines += [
            "## Sequential design", "",
            f"{_METHOD_LABELS[seq.method]} alpha spending, look {seq.current_look} of "
            f"{seq.planned_looks}{' (final)' if seq.is_final else ''}. At this look the result "
            f"is significant only if the absolute z statistic reaches {_num(seq.critical_value)}"
            f", i.e. p < {seq.nominal_alpha:.3g}. Alpha spent so far: "
            f"{seq.cumulative_alpha:.3g} of {seq.overall_alpha:.3g}. Intervals above are "
            "repeated confidence intervals.", "",
            "Planned boundaries:", "", render_boundaries(seq.plan, seq.current_look), "",
        ]
    lines += ["## Diagnostics", ""]
    for d in report.diagnostics:
        mark = "N/A" if not d.assessed else ("OK" if d.passed else d.severity.upper())
        lines.append(f"- **{mark}** `{safe_text(d.name)}` — {safe_text(d.message)}")
    nov = report.novelty
    if nov is not None and nov.assessed:
        lines += ["", "## Effect over time (novelty check)", "",
                  "| Period | n (C / T) | Effect | SE |", "|---|---|---|---|"]
        lines += [f"| {safe_text(q.label)} | {q.n_control:,} / {q.n_treatment:,} | "
                  f"{q.effect:+.5g} | {q.std_error:.3g} |" for q in nov.periods]
    seg = report.segments
    if seg is not None:
        lines += [
            "", "## Segments (exploratory)", "", f"> {seg.label}", "",
            f"| {safe_text(seg.segment_col)} | n (C / T) | Effect | Simultaneous "
            f"{confidence_level(seg.alpha)} CI | p | Adjusted p ({seg.correction}) |",
            "|---|---|---|---|---|---|",
        ]
        for s in seg.segments:
            e = s.estimate
            lines.append(
                f"| {safe_text(s.segment)} | {e.n_control:,} / {e.n_treatment:,} | "
                f"{e.absolute_effect:+.5g} | [{s.simultaneous_ci_low:+.5g}, "
                f"{s.simultaneous_ci_high:+.5g}] | {e.p_value:.4g} | {s.adjusted_p_value:.4g} |")
        lines += [f"| {safe_text(k.segment)} | {k.n_control:,} / {k.n_treatment:,} | not "
                  f"analysed: {safe_text(k.reason)} | | | |" for k in seg.skipped]
        if seg.q_statistic is not None:
            lines += ["", f"Heterogeneity (Cochran's Q): Q = {seg.q_statistic:.2f} on "
                      f"{seg.q_dof} df, p = {seg.q_p_value:.3g}, I^2 = {seg.i_squared:.0%}."]
    lines += ["", "## Assumptions", "", *[f"- {safe_text(a)}" for a in report.assumptions], ""]
    return "\n".join(lines)


def render_simulations(results: list[SimulationResult]) -> str:
    lines = ["| Check | Estimate | Expected | Tolerance | MC SE | Sims | Result |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        exp = "n/a" if r.expected is None else f"{r.expected:.4f}"
        tol = "n/a" if r.tolerance is None else f"{r.tolerance:.4f}"
        verdict = "info" if r.passed is None else ("PASS" if r.passed else "FAIL")
        lines.append(f"| {r.name} | {r.estimate:.4f} | {exp} | {tol} | "
                     f"{r.mc_standard_error:.4f} | {r.n_sims} | {verdict} |")
    return "\n".join(lines)
