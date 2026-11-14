import numpy as np
import pytest
from scipy import stats

from ab_testing_copilot import analysis as an
from ab_testing_copilot import diagnostics as dg
from ab_testing_copilot.decision import decide, evaluate_guardrail
from ab_testing_copilot.models import Decision


def test_srm_matches_scipy_and_flags():
    d = dg.srm_check(5000, 5300)
    assert d.p_value == pytest.approx(stats.chisquare([5000, 5300]).pvalue)
    assert not dg.srm_check(5000, 5400).passed
    assert dg.srm_check(5000, 5400).severity == "blocking"
    assert dg.srm_check(5000, 5050).passed
    assert dg.srm_check(2000, 8000, expected_treatment_share=0.8).passed
    assert not dg.srm_check(2000, 8000).passed


@pytest.mark.parametrize("args", [(0, 0, 0.5), (-1, 5, 0.5), (5, 5, 0.0), (5, 5, 1.0)])
def test_srm_invalid(args):
    with pytest.raises(ValueError):
        dg.srm_check(*args)


def test_missing_data():
    assert dg.missing_data_check(0, 100, 0, 100).severity == "info"
    minor = dg.missing_data_check(50, 5000, 55, 5000)
    assert minor.severity == "warning" and minor.passed
    assert not dg.missing_data_check(1000, 5000, 1010, 5000).passed
    bad = dg.missing_data_check(50, 5000, 400, 5000)
    assert bad.severity == "blocking" and not bad.passed


def test_outlier_check():
    rng = np.random.default_rng(0)
    clean = rng.normal(50, 5, 1000)
    assert dg.outlier_check(clean, "control").passed
    dirty = clean.copy()
    dirty[0] = 1e7
    assert not dg.outlier_check(dirty, "control").passed
    assert dg.outlier_check([1.0, 2.0], "control").passed


def test_covariate_balance():
    rng = np.random.default_rng(0)
    assert dg.covariate_balance_check(rng.normal(0, 1, 5000), rng.normal(0, 1, 5000)).passed
    assert not dg.covariate_balance_check(rng.normal(0, 1, 5000), rng.normal(0.5, 1, 5000)).passed


def test_peeking():
    assert dg.peeking_check(1, 0.05).passed
    assert not dg.peeking_check(4, 0.05).passed
    with pytest.raises(ValueError):
        dg.peeking_check(0, 0.05)


def _ok():
    return [dg.srm_check(5000, 5000)]


def test_decide_ship_do_not_ship_inconclusive():
    win = an.compare_proportions(480, 5000, 600, 5000)
    loss = an.compare_proportions(600, 5000, 480, 5000)
    flat = an.compare_proportions(500, 5000, 505, 5000)
    assert decide(win, [], _ok()).decision is Decision.SHIP
    assert decide(win, [], _ok()).evidence_quality == "strong"
    assert decide(loss, [], _ok()).decision is Decision.DO_NOT_SHIP
    assert decide(flat, [], _ok()).decision is Decision.INCONCLUSIVE
    # direction flips when lower is better
    assert decide(loss, [], _ok(), higher_is_better=False).decision is Decision.SHIP
    assert decide(win, [], _ok(), higher_is_better=False).decision is Decision.DO_NOT_SHIP


def test_decide_mde_messages():
    flat = an.compare_proportions(5000, 50000, 5010, 50000)
    r = decide(flat, [], _ok(), absolute_mde=0.02)
    assert any("ruled out" in x for x in r.reasons)
    small = an.compare_proportions(50, 500, 52, 500)
    r = decide(small, [], _ok(), absolute_mde=0.02)
    assert any("underpowered" in x for x in r.reasons)


def test_blocking_diagnostic_overrides_a_win():
    win = an.compare_proportions(480, 5000, 600, 5400)
    r = decide(win, [], [dg.srm_check(5000, 5400)])
    assert r.decision is Decision.INCONCLUSIVE and r.evidence_quality == "invalid"


def test_guardrails():
    rng = np.random.default_rng(0)
    base = rng.normal(100, 10, 5000)
    ok = evaluate_guardrail(an.compare_means(base, rng.normal(100, 10, 5000)), True, 0.02)
    bad = evaluate_guardrail(an.compare_means(base, rng.normal(95, 10, 5000)), True, 0.02)
    noisy = evaluate_guardrail(an.compare_means(base[:40], rng.normal(100, 10, 40)), True, 0.02)
    lower = evaluate_guardrail(an.compare_means(base, rng.normal(105, 10, 5000)), False, 0.02)
    assert (ok.status, bad.status, noisy.status, lower.status) == (
        "pass", "fail", "uncertain", "fail")
    win = an.compare_proportions(480, 5000, 600, 5000)
    assert decide(win, [ok], _ok()).decision is Decision.SHIP
    assert decide(win, [bad], _ok()).decision is Decision.DO_NOT_SHIP
    assert decide(win, [noisy], _ok()).decision is Decision.INCONCLUSIVE
    relaxed = decide(win, [noisy], _ok(), require_guardrail_noninferiority=False)
    assert relaxed.decision is Decision.SHIP and relaxed.evidence_quality == "moderate"
    with pytest.raises(ValueError):
        evaluate_guardrail(win, True, -0.1)


def test_guardrail_absolute_fallback():
    e = an.compare_means([-5.0, -4.0, -6.0, -5.5] * 50, [-5.0, -4.1, -6.0, -5.4] * 50)
    g = evaluate_guardrail(e, True, 1.0)
    assert g.status == "pass" and "absolute" in g.message
