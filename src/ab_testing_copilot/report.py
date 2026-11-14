"""Markdown rendering of decision reports."""

from __future__ import annotations

from ab_testing_copilot.models import DecisionReport, EffectEstimate, SimulationResult


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.2%}"


def _effect_row(e: EffectEstimate) -> str:
    rel = (f"{_pct(e.relative_effect)} [{_pct(e.rel_ci_low)}, {_pct(e.rel_ci_high)}]"
           if e.relative_effect is not None else "n/a")
    return (f"| {e.metric} | {e.control_value:.5g} | {e.treatment_value:.5g} | "
            f"{e.absolute_effect:+.5g} [{e.ci_low:+.5g}, {e.ci_high:+.5g}] | {rel} | "
            f"{e.p_value:.4g} | {e.n_control:,} / {e.n_treatment:,} |")


def render_markdown(report: DecisionReport, title: str = "Experiment decision report") -> str:
    """Human-readable report. Contains only quantities computed from the data."""
    p = report.primary
    lines = [
        f"# {title}", "",
        f"**Recommendation: {report.decision.value}**  ",
        f"Evidence quality: **{report.evidence_quality}**  ",
        f"Confidence level for the primary metric: {1 - report.effective_alpha:.2%}", "",
        "## Why", "", *[f"- {r}" for r in report.reasons], "",
        "## Effects", "",
        "| Metric | Control | Treatment | Absolute effect [CI] | Relative effect [CI] | p "
        "| n (C / T) |",
        "|---|---|---|---|---|---|---|",
        _effect_row(p), *[_effect_row(g.estimate) for g in report.guardrails], "",
        f"Primary method: {p.method}.", "",
    ]
    if report.guardrails:
        lines += ["## Guardrails", "",
                  *[f"- **{g.status.upper()}** — {g.message}" for g in report.guardrails], ""]
    lines += ["## Diagnostics", ""]
    for d in report.diagnostics:
        mark = "OK" if d.passed else d.severity.upper()
        lines.append(f"- **{mark}** `{d.name}` — {d.message}")
    lines += ["", "## Assumptions", "", *[f"- {a}" for a in report.assumptions], ""]
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
