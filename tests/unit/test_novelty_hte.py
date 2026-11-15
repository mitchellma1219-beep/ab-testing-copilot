"""Novelty trend and exploratory heterogeneity: the pure statistical parts."""

import math

import numpy as np
import pytest
from scipy.stats import t as student_t

from ab_testing_copilot import heterogeneity as ht
from ab_testing_copilot import novelty as nv
from ab_testing_copilot.analysis import compare_proportions
from ab_testing_copilot.models import PeriodEffect


def _periods(effects, se=0.01, n=1000):
    return [PeriodEffect(index=i, label=f"day {i}", n_control=n, n_treatment=n, effect=e,
                         std_error=se) for i, e in enumerate(effects)]


def test_trend_on_an_exact_line():
    # y = 1 - 0.1 x, equal standard errors of 0.1: Sxx = 100 * 10, slope SE = sqrt(1 / 1000).
    slope, se, stat, dof, p, mean = nv.effect_trend(
        [0, 1, 2, 3, 4], [1.0, 0.9, 0.8, 0.7, 0.6], [0.1] * 5)
    assert slope == pytest.approx(-0.1) and mean == pytest.approx(0.8)
    assert se == pytest.approx(math.sqrt(1 / 1000)) and dof == 3
    assert stat == pytest.approx(-math.sqrt(10))
    assert p == pytest.approx(2 * student_t.sf(math.sqrt(10), 3))  # 0.0508 on 3 df


def test_trend_weights_precise_periods_more():
    # The last point is far off but very imprecise: it barely moves the weighted slope.
    slope, *_ = nv.effect_trend([0, 1, 2, 3], [1.0, 1.0, 1.0, 9.0], [0.1, 0.1, 0.1, 100.0])
    assert abs(slope) < 1e-4


def test_trend_widens_when_periods_scatter_more_than_their_standard_errors():
    y = [0.0, 0.5, -0.4, 0.6, -0.5, 0.4]
    _, tight, _, _, p_tight, _ = nv.effect_trend(range(6), y, [1.0] * 6)
    _, wide, _, _, p_wide, _ = nv.effect_trend(range(6), y, [0.01] * 6)
    # with SE = 1 the scatter is explained (scale 1); with SE = 0.01 it is not, so the slope
    # SE is inflated by the residual scale instead of shrinking 100-fold.
    assert tight == pytest.approx(math.sqrt(1 / 17.5))
    assert wide > 0.1 * tight and p_wide > 0.5 and p_tight > 0.5


@pytest.mark.parametrize("args", [
    ([0, 1], [1.0, 2.0], [0.1, 0.1]), ([0, 1, 2], [1.0, 2.0], [0.1, 0.1, 0.1]),
    ([0, 1, 2], [1.0, 2.0, 3.0], [0.1, 0.0, 0.1]), ([0, 1, 2], [1.0, float("nan"), 3.0], [0.1] * 3),
    ([1, 1, 1], [1.0, 2.0, 3.0], [0.1] * 3),
])
def test_trend_rejects_bad_input(args):
    with pytest.raises(ValueError):
        nv.effect_trend(*args)


def test_decay_towards_zero_is_flagged_with_its_evidence():
    res = nv.assess_novelty(_periods([0.08 - 0.01 * i for i in range(8)]))
    assert res.assessed and res.decay_detected and not res.growth_detected
    assert res.slope == pytest.approx(-0.01) and res.p_value < 0.001
    assert res.fitted_start == pytest.approx(0.08) and res.fitted_end == pytest.approx(0.01)
    assert res.early_effect > res.late_effect
    for needle in ("slope", "first-half", "warning, not proof", "seasonality"):
        assert needle in res.message
    diag = nv.novelty_diagnostic(res)
    assert diag.severity == "warning" and not diag.passed and diag.p_value == res.p_value


def test_a_fading_harm_is_also_a_decay():
    res = nv.assess_novelty(_periods([-0.08 + 0.01 * i for i in range(8)]))
    assert res.decay_detected and res.slope > 0


def test_a_growing_effect_is_reported_but_is_not_a_novelty_warning():
    res = nv.assess_novelty(_periods([0.01 * i for i in range(1, 9)]))
    assert res.growth_detected and not res.decay_detected
    diag = nv.novelty_diagnostic(res)
    assert diag.passed and diag.severity == "info" and "understate" in res.message


def test_a_trend_through_zero_is_a_reversal_unless_the_overshoot_is_small():
    # from -0.04 to +0.03: the effect changed sign; that is not "fading towards zero"
    flip = nv.assess_novelty(_periods([-0.04 + 0.01 * i for i in range(8)]))
    assert flip.reversal_detected and not flip.decay_detected and not flip.growth_detected
    assert "changes sign" in flip.message and nv.novelty_diagnostic(flip).passed
    # from +0.07 to -0.01: an effect that fades and slightly overshoots is still a decay
    fade = nv.assess_novelty(_periods([0.07 - 0.01 * i for i in range(9)]))
    assert fade.decay_detected and not fade.reversal_detected
    assert abs(fade.fitted_end) <= nv.OVERSHOOT_RATIO * abs(fade.fitted_start)
    # just inside the limit (start +0.040, end -0.019) is fading; well beyond it is not
    inside = nv.assess_novelty(_periods([0.04 - 0.0098 * i for i in range(7)]))
    assert inside.decay_detected
    past = nv.assess_novelty(_periods([0.04 - 0.01 * i for i in range(8)]))
    assert past.reversal_detected and not past.decay_detected


def test_a_stable_effect_passes_without_claiming_absence():
    res = nv.assess_novelty(_periods([0.02, 0.021, 0.019, 0.02, 0.022, 0.018]))
    assert res.assessed and not res.decay_detected and not res.growth_detected
    assert "does not rule out" in res.message and nv.novelty_diagnostic(res).passed


def test_too_few_or_degenerate_periods_are_not_assessed():
    few = nv.assess_novelty(_periods([0.05, 0.03, 0.01, 0.0]))
    assert not few.assessed and "only 4 usable period(s)" in few.message
    diag = nv.novelty_diagnostic(few)
    assert diag.passed and not diag.assessed and diag.severity == "info"
    flat = _periods([0.05, 0.04, 0.03, 0.02, 0.01, 0.0])
    degenerate = [p.model_copy(update={"std_error": 0.0}) if i < 3 else p
                  for i, p in enumerate(flat)]
    res = nv.assess_novelty(degenerate)
    assert not res.assessed and res.excluded_periods == 3
    same_day = [p.model_copy(update={"index": i % 2}) for i, p in enumerate(flat)]
    assert not nv.assess_novelty(same_day).assessed
    with pytest.raises(ValueError):
        nv.assess_novelty(flat, alpha=0)


def test_excluded_periods_and_undated_rows_are_disclosed():
    res = nv.assess_novelty(_periods([0.02] * 6), excluded_periods=2, rows_without_date=40)
    assert "2 period(s) were left out" in res.message and "40 row(s)" in res.message
    assert res.excluded_periods == 2 and res.rows_without_date == 40


def test_cochran_q_worked_example():
    # effects 0.01, 0.02, 0.05 with SE 0.01: pooled 0.08 / 3, Q = 26 / 3 on 2 df, and for 2 df
    # the chi-square tail is exp(-Q / 2).
    q, dof, p, i2, pooled = ht.cochran_q([0.01, 0.02, 0.05], [0.01] * 3)
    assert pooled == pytest.approx(0.08 / 3) and q == pytest.approx(26 / 3) and dof == 2
    assert p == pytest.approx(math.exp(-13 / 3)) and i2 == pytest.approx((26 / 3 - 2) / (26 / 3))
    same = ht.cochran_q([0.02, 0.02], [0.01, 0.03])
    assert same[0] == 0 and same[2] == 1.0 and same[3] == 0.0


@pytest.mark.parametrize("args", [
    ([0.01], [0.01]), ([0.01, 0.02], [0.01]), ([0.01, 0.02], [0.01, 0.0]),
    ([0.01, float("inf")], [0.01, 0.01]),
])
def test_cochran_q_rejects_bad_input(args):
    with pytest.raises(ValueError):
        ht.cochran_q(*args)


def _segment(xc, nc, xt, nt, alpha=0.05):
    return compare_proportions(xc, nc, xt, nt, alpha)


def test_summarise_segments_applies_the_correction_and_labels_the_result():
    cells = {"a": (100, 1000, 150, 1000), "b": (100, 1000, 104, 1000),
             "c": (100, 1000, 131, 1000)}
    est = {k: _segment(*v) for k, v in cells.items()}
    sim = {k: _segment(*v, alpha=0.05 / 3) for k, v in cells.items()}
    res = ht.summarise_segments(est, sim, "plan", 0.05, "holm")
    assert res.exploratory is True and "Exploratory" in res.label
    raw = [est[k].p_value for k in "abc"]
    assert [s.adjusted_p_value for s in res.segments] == pytest.approx(
        [min(1, raw[0] * 3), min(1.0, max(raw[1], raw[2] * 2)), min(1, raw[2] * 2)])
    assert [s.significant_after_correction for s in res.segments] == [True, False, False]
    assert raw[2] < 0.05  # segment c is "significant" only before the correction
    for s, k in zip(res.segments, "abc", strict=True):
        assert s.simultaneous_ci_low < est[k].ci_low < est[k].ci_high < s.simultaneous_ci_high
    q, dof, p_het, i2, pooled = ht.cochran_q(
        [est[k].absolute_effect for k in "abc"], [est[k].std_error for k in "abc"])
    assert (res.q_statistic, res.q_dof, res.q_p_value, res.i_squared, res.pooled_effect) == (
        q, dof, p_het, i2, pooled)
    assert dof == 2 and 0 < i2 < 1 and res.heterogeneity_detected is (p_het < 0.05)
    opposite = {"up": _segment(100, 1000, 180, 1000), "down": _segment(100, 1000, 60, 1000)}
    assert ht.summarise_segments(opposite, opposite, "plan", 0.05).heterogeneity_detected
    assert "do not change the recommendation" in res.message
    diag = ht.segment_diagnostic(res)
    assert diag.passed and diag.severity == "info" and diag.assessed
    fdr = ht.summarise_segments(est, sim, "plan", 0.05, "benjamini-hochberg")
    assert "false discovery rate" in fdr.message
    with pytest.raises(ValueError):
        ht.summarise_segments(est, {"a": sim["a"]}, "plan", 0.05)


def test_single_usable_segment_has_no_heterogeneity_test():
    est = {"only": _segment(100, 1000, 130, 1000)}
    res = ht.summarise_segments(est, est, "plan", 0.05)
    assert res.q_statistic is None and not res.heterogeneity_detected
    assert "Too few usable segments" in res.message
    missing = ht.segment_diagnostic(None, "column 'x' has fewer than 2 levels.")
    assert missing.passed and not missing.assessed and "not run" in missing.message


def test_q_statistic_is_invariant_to_a_common_shift():
    rng = np.random.default_rng(0)
    e, se = rng.normal(0.02, 0.01, 6), rng.uniform(0.005, 0.02, 6)
    assert ht.cochran_q(e, se)[0] == pytest.approx(ht.cochran_q(e + 0.3, se)[0])
    assert np.isclose(ht.cochran_q(e, se)[4] + 0.3, ht.cochran_q(e + 0.3, se)[4])
