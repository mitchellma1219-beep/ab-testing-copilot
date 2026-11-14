"""Decision engine: Ship / Do not ship / Inconclusive with explicit reasons."""

from __future__ import annotations

from typing import Literal

from ab_testing_copilot.models import (
    Decision,
    DecisionReport,
    Diagnostic,
    EffectEstimate,
    GuardrailResult,
)


def evaluate_guardrail(
    estimate: EffectEstimate, higher_is_better: bool, margin: float
) -> GuardrailResult:
    """Non-inferiority check. ``margin`` is the tolerated relative harm (e.g. 0.02 = 2%).

    Falls back to absolute units when the relative effect is undefined (control <= 0).
    """
    if margin < 0:
        raise ValueError("guardrail margin must be >= 0")
    sign = 1.0 if higher_is_better else -1.0
    if estimate.rel_ci_low is not None and estimate.rel_ci_high is not None:
        lo, hi, unit = estimate.rel_ci_low, estimate.rel_ci_high, "relative"
    else:
        lo, hi, unit = estimate.ci_low, estimate.ci_high, "absolute"
    harm_lo, harm_hi = sorted((-sign * lo, -sign * hi))
    status: Literal["pass", "fail", "uncertain"]
    if harm_lo > 0:
        status = "fail"
        msg = (f"{estimate.metric}: statistically significant regression "
               f"({unit} harm between {harm_lo:.4g} and {harm_hi:.4g}).")
    elif harm_hi < margin:
        status = "pass"
        msg = (f"{estimate.metric}: harm larger than the {margin:.4g} {unit} margin is ruled out "
               f"(worst case {max(harm_hi, 0):.4g}).")
    else:
        status = "uncertain"
        msg = (f"{estimate.metric}: cannot rule out harm up to {harm_hi:.4g} ({unit}), "
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
) -> DecisionReport:
    """Combine validity checks, the primary effect and guardrails into one recommendation.

    ``primary`` must already be computed at the effective alpha (after any peeking penalty).
    """
    sign = 1.0 if higher_is_better else -1.0
    good_lo, good_hi = sorted((sign * primary.ci_low, sign * primary.ci_high))
    blocking = [d for d in diagnostics if d.severity == "blocking" and not d.passed]
    soft = [d for d in diagnostics if d.severity == "warning" and not d.passed]
    failed = [g for g in guardrails if g.status == "fail"]
    uncertain = [g for g in guardrails if g.status == "uncertain"]
    reasons: list[str] = []
    ci = f"{1 - primary.alpha:.1%} CI [{primary.ci_low:.4g}, {primary.ci_high:.4g}]"
    effect = f"{primary.metric} effect {primary.absolute_effect:+.4g} ({ci})"

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
    elif good_lo > 0:
        if uncertain and require_guardrail_noninferiority:
            decision = Decision.INCONCLUSIVE
            reasons.append(f"The primary metric improved ({effect}), but guardrails are not "
                           "cleared.")
            reasons.extend(g.message for g in uncertain)
        else:
            decision = Decision.SHIP
            reasons.append(f"The primary metric improved: {effect}.")
            reasons.extend(g.message for g in guardrails)
    else:
        decision = Decision.INCONCLUSIVE
        reasons.append(f"The interval includes zero: {effect}.")
        if absolute_mde is not None:
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
        assumptions=assumptions or [], effective_alpha=primary.alpha,
    )
