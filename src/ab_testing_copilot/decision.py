"""Decision engine: Ship / Do not ship / Inconclusive with explicit reasons."""

from __future__ import annotations

import math
from typing import Literal

from ab_testing_copilot.models import (
    Decision,
    DecisionReport,
    Diagnostic,
    EffectEstimate,
    GuardrailResult,
    SequentialLook,
)

_METHOD_LABELS = {"obrien-fleming": "O'Brien-Fleming-type", "pocock": "Pocock-type"}


def confidence_level(alpha: float) -> str:
    """``1 - alpha`` as a percentage with enough digits never to round up to 100%."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    if alpha < 1e-10:
        return f"(1 - {alpha:.1e})"
    decimals = max(1, math.ceil(-math.log10(alpha)) - 1)
    return f"{(1 - alpha) * 100:.{decimals}f}%"


def _harm_interval(estimate: EffectEstimate, higher_is_better: bool) -> tuple[float, float, str]:
    """Interval for the harm (positive = worse), in relative units when they are defined."""
    sign = 1.0 if higher_is_better else -1.0
    if estimate.rel_ci_low is not None and estimate.rel_ci_high is not None:
        lo, hi, unit = estimate.rel_ci_low, estimate.rel_ci_high, "relative"
    else:
        lo, hi, unit = estimate.ci_low, estimate.ci_high, "absolute"
    harm_lo, harm_hi = sorted((-sign * lo, -sign * hi))
    return harm_lo, harm_hi, unit


def evaluate_guardrail(
    estimate: EffectEstimate, higher_is_better: bool, margin: float,
    noninferiority: EffectEstimate | None = None,
) -> GuardrailResult:
    """Non-inferiority check. ``margin`` is the tolerated relative harm (e.g. 0.02 = 2%).

    Falls back to absolute units when the relative effect is undefined (control <= 0).
    ``noninferiority`` is an optional second estimate of the same metric with a wider
    interval. When given, a regression is still flagged from ``estimate`` but harm beyond the
    margin must be ruled out by the wider interval. This keeps harm detection sensitive and
    makes "safe" harder to claim when results were inspected more than once.
    """
    if margin < 0:
        raise ValueError("guardrail margin must be >= 0")
    harm_lo, harm_hi, unit = _harm_interval(estimate, higher_is_better)
    strict = noninferiority if noninferiority is not None else estimate
    _, strict_hi, _ = _harm_interval(strict, higher_is_better)
    level = "" if noninferiority is None else f" at the {confidence_level(strict.alpha)} level"
    status: Literal["pass", "fail", "uncertain"]
    if harm_lo > 0:
        status = "fail"
        msg = (f"{estimate.metric}: statistically significant regression "
               f"({unit} harm between {harm_lo:.4g} and {harm_hi:.4g}).")
    elif strict_hi < margin:
        status = "pass"
        msg = (f"{estimate.metric}: harm larger than the {margin:.4g} {unit} margin is ruled out"
               f"{level} (worst case {max(strict_hi, 0):.4g}).")
    else:
        status = "uncertain"
        msg = (f"{estimate.metric}: cannot rule out harm up to {strict_hi:.4g} ({unit}){level}, "
               f"which exceeds the {margin:.4g} margin.")
    return GuardrailResult(estimate=estimate, status=status, margin=margin, message=msg)


def decide(
    primary: EffectEstimate,
    guardrails: list[GuardrailResult],
    diagnostics: list[Diagnostic],
    higher_is_better: bool = True,
    absolute_mde: float | None = None,
    require_guardrail_noninferiority: bool = True,
    assumptions: list[str] | None = None,
    sequential: SequentialLook | None = None,
) -> DecisionReport:
    """Combine validity checks, the primary effect and guardrails into one recommendation.

    ``primary`` must already be computed at the effective alpha (after any peeking penalty or
    at the nominal level of the sequential look). ``sequential`` only changes the wording: at
    an interim look "Inconclusive" means "continue", never "no effect".
    """
    sign = 1.0 if higher_is_better else -1.0
    good_lo, good_hi = sorted((sign * primary.ci_low, sign * primary.ci_high))
    blocking = [d for d in diagnostics if d.severity == "blocking" and not d.passed]
    soft = [d for d in diagnostics if d.severity == "warning" and not d.passed]
    failed = [g for g in guardrails if g.status == "fail"]
    uncertain = [g for g in guardrails if g.status == "uncertain"]
    reasons: list[str] = []
    ci = f"{confidence_level(primary.alpha)} CI [{primary.ci_low:.4g}, {primary.ci_high:.4g}]"
    effect = f"{primary.metric} effect {primary.absolute_effect:+.4g} ({ci})"
    interim = sequential is not None and not sequential.is_final
    crossed = ""
    carry_on = ""
    if sequential is not None:
        where = f"look {sequential.current_look} of {sequential.planned_looks}"
        label = _METHOD_LABELS[sequential.method]
        bound = f"absolute z of at least {sequential.critical_value:.4g}"
        crossed = f"The pre-registered {label} boundary ({bound}) was crossed at {where}."
        if interim:
            crossed += (" Estimates at an early stop overstate the effect on average; no bias "
                        "adjustment is applied.")
            carry_on = (f"Interim {where}: the {label} boundary ({bound}) was not crossed. "
                        "Continue to the next planned look. This is not evidence of no effect, "
                        "and the design has no futility rule.")

    quality: Literal["strong", "moderate", "weak", "invalid"]
    if blocking:
        decision, quality = Decision.INCONCLUSIVE, "invalid"
        reasons.append("The experiment failed validity checks; the effect estimate is not "
                       "trustworthy and must not be used for a launch decision.")
        reasons.extend(d.message for d in blocking)
    elif failed:
        decision = Decision.DO_NOT_SHIP
        reasons.extend(g.message for g in failed)
        reasons.append(f"Primary result for context: {effect}.")
    elif good_hi < 0:
        decision = Decision.DO_NOT_SHIP
        reasons.append(f"The primary metric moved in the harmful direction: {effect}.")
        if crossed:
            reasons.append(crossed)
    elif good_lo > 0:
        if uncertain and require_guardrail_noninferiority:
            decision = Decision.INCONCLUSIVE
            reasons.append(f"The primary metric improved ({effect}), but guardrails are not "
                           "cleared.")
            reasons.extend(g.message for g in uncertain)
            if interim:
                reasons.append("Continue to the next planned look to resolve the guardrails.")
        else:
            decision = Decision.SHIP
            reasons.append(f"The primary metric improved: {effect}.")
            if crossed:
                reasons.append(crossed)
            reasons.extend(g.message for g in guardrails)
    else:
        decision = Decision.INCONCLUSIVE
        reasons.append(f"The interval includes zero: {effect}.")
        if interim:
            reasons.append(carry_on)
        elif absolute_mde is not None:
            if good_hi < abs(absolute_mde):
                reasons.append(f"Improvements as large as the MDE ({abs(absolute_mde):.4g}) are "
                               "ruled out, so more data is unlikely to reveal a worthwhile win.")
            else:
                reasons.append(f"The interval still includes the MDE ({abs(absolute_mde):.4g}): "
                               "the test is underpowered for the effect of interest.")
    if not blocking:
        if soft or primary.warnings:
            quality = "weak"
        elif uncertain:
            quality = "moderate"
        else:
            quality = "strong"
        reasons.extend(d.message for d in soft)
        reasons.extend(primary.warnings)
    return DecisionReport(
        decision=decision, evidence_quality=quality, reasons=reasons, primary=primary,
        guardrails=guardrails, diagnostics=diagnostics,
        assumptions=assumptions or [], effective_alpha=primary.alpha, sequential=sequential,
    )
