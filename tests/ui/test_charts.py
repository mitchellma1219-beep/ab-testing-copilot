"""Chart builders: pure functions from results to Plotly figures, each with a table twin."""

import json

import numpy as np
import pytest

pytest.importorskip("plotly")

from ab_testing_copilot import charts, design
from ab_testing_copilot import sequential as sq
from ab_testing_copilot.aa import aa_check
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
)
from ab_testing_copilot.sequential import SequentialDesign
from ab_testing_copilot.synthetic import make_experiment, make_scenario

BIN = MetricSpec(column="converted", type="binary")
LOAD = GuardrailSpec(column="page_load_ms", type="continuous", higher_is_better=False)
LIGHT, DARK = charts.THEMES["light"], charts.THEMES["dark"]


@pytest.fixture(scope="module")
def report():
    return analyze_experiment(make_scenario("clean_win"), ExperimentConfig(
        primary=BIN, guardrails=[LOAD], unit_col="user_id", date_col="exposure_date",
        segment_col="segment"))


def _spec(fig):
    """The figure as the JSON that is sent to the browser."""
    return json.loads(fig.to_json())


def _axes(fig):
    return sorted(k for k in _spec(fig)["layout"] if k.startswith(("xaxis", "yaxis")))


def _named(fig):
    return [t.name for t in fig.data if t.showlegend is not False and t.name]


def _check_common(fig, mode="light"):
    theme = charts.THEMES[mode]
    layout = fig.layout
    assert _axes(fig) == ["xaxis", "yaxis"]  # one value axis: never a second y scale
    assert layout.paper_bgcolor == theme.surface and layout.plot_bgcolor == theme.surface
    assert layout.title.font.color == theme.ink and layout.font.family == charts.FONT
    assert layout.title.text and layout.xaxis.griddash == "solid"
    assert bool(layout.showlegend) is (len(_named(fig)) >= 2)  # a legend only for 2+ series
    colours = {theme.series[0], theme.series[1], theme.context, theme.ink_secondary,
               theme.surface}
    for trace in fig.data:
        for part in (getattr(trace, "line", None), getattr(trace, "marker", None)):
            colour = getattr(part, "color", None)
            assert colour is None or colour in colours, colour


def test_theme_uses_the_validated_palette_in_a_fixed_order():
    assert LIGHT.series == ("#2a78d6", "#eb6834") and DARK.series == ("#3987e5", "#d95926")
    assert (LIGHT.surface, DARK.surface) == ("#fcfcfb", "#1a1a19")
    with pytest.raises(ValueError):
        charts.empty_figure("x", mode="sepia")  # type: ignore[arg-type]


def test_power_curve(report):
    size = design.sample_size_for_proportions(0.10, 0.02)
    points = design.power_curve("binary", 0.02, 2 * size.n_control, baseline=0.10)
    assert [p for _, p in points] == sorted(p for _, p in points) and len(points) == 60
    assert points[-1][0] == 2 * size.n_control and 0.95 < points[-1][1] < 1
    fig = charts.power_curve_figure(points, 0.8, size.n_control)
    _check_common(fig)
    assert fig.data[0].line.width == 2 and fig.data[0].line.color == LIGHT.series[0]
    assert fig.layout.hovermode == "x unified" and fig.layout.xaxis.showspikes
    marker = fig.data[-1]
    assert list(marker.x) == [size.n_control] and marker.y[0] == pytest.approx(0.8, abs=0.01)
    assert marker.marker.line.color == LIGHT.surface and marker.marker.line.width == 2
    texts = [a.text for a in fig.layout.annotations]
    assert "3,841 per arm" in texts and "target 80%" in texts
    two = charts.power_curve_figure(points, 0.8, size.n_control, comparison=points, mode="dark")
    _check_common(two, "dark")
    assert _named(two) == ["Fixed horizon", "Group sequential"]
    assert two.data[1].line.color == DARK.series[1]
    with pytest.raises(ValueError):
        charts.power_curve_figure(points[:1], 0.8, 10)


def test_power_curve_helper_validates_and_supports_means():
    cont = design.power_curve("continuous", 1.0, 3000, std_dev=10, allocation_ratio=2.0)
    n, power = cont[-1]
    assert power == pytest.approx(design.power_for_means(10, 1.0, n, 2 * n))
    assert design.mde_for_means(10, 1570, 1570) == pytest.approx(1.0, abs=1e-3)
    for kwargs in ({"metric_type": "ratio"}, {"n_control_max": 1}, {"points": 1},
                   {"allocation_ratio": 0}):
        with pytest.raises(ValueError):
            design.power_curve(**{"metric_type": "binary", "absolute_effect": 0.02,
                                  "n_control_max": 1000, "baseline": 0.1, **kwargs})
    for args in ((0, 10, 10), (1, 0, 10)):
        with pytest.raises(ValueError):
            design.mde_for_means(*args)


def test_effects_figure_and_table(report):
    fig = charts.effects_figure(report)
    _check_common(fig)
    trace = fig.data[0]
    assert list(trace.y) == ["converted  (primary)", "page_load_ms  (guardrail: pass)"]
    assert trace.x[0] == pytest.approx(report.primary.relative_effect)
    assert trace.error_x.array[0] == pytest.approx(
        report.primary.rel_ci_high - report.primary.relative_effect)
    assert trace.marker.size >= 8 and trace.error_x.thickness == 2
    assert fig.layout.xaxis.rangemode == "tozero" and fig.layout.xaxis.zeroline
    assert "95.0% interval" in fig.layout.title.subtitle.text
    rows = charts.effects_rows(report)
    assert [r["metric"] for r in rows] == ["converted", "page_load_ms"]
    assert rows[0]["role"] == "primary" and rows[1]["guardrail status"] == "pass"
    assert rows[0]["absolute effect"] == report.primary.absolute_effect
    assert rows[0]["p-value"] == report.primary.p_value


def test_effects_figure_without_relative_effects_says_so():
    df = make_experiment(n=2000)
    df["delta"] = df["revenue"] - 100  # control mean below zero: relative effect undefined
    r = analyze_experiment(df, ExperimentConfig(
        primary=MetricSpec(column="delta", type="continuous")))
    assert r.primary.relative_effect is None
    fig = charts.effects_figure(r)
    assert not fig.data and "undefined" in fig.layout.annotations[0].text
    assert charts.effects_rows(r)[0]["relative effect"] is None


def test_boundaries_figure():
    df = make_experiment(n=8000, lift=0.03).iloc[:4000]
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, sequential=SequentialDesign(
        method="obrien-fleming", planned_looks=4, current_look=2, planned_sample_size=8000)))
    fig = charts.boundaries_figure(r.sequential.plan, r.primary.statistic, 2)
    _check_common(fig)
    upper, lower, seen = fig.data
    assert list(upper.y) == pytest.approx(r.sequential.plan.critical_values)
    assert list(lower.y) == pytest.approx([-c for c in r.sequential.plan.critical_values])
    assert seen.marker.color == LIGHT.series[1] and list(seen.x) == [2]
    assert _named(fig) == ["Stopping boundary", "Observed z at this look"]
    assert any(a.text == f"z = {r.primary.statistic:+.2f}" for a in fig.layout.annotations)
    rows = charts.boundary_rows(r.sequential.plan)
    assert [row["look"] for row in rows] == [1, 2, 3, 4]
    assert rows[1]["critical value (abs z)"] == pytest.approx(2.9631, abs=5e-5)
    plan_only = charts.boundaries_figure(sq.sequential_boundaries(3, 0.05, "pocock"))
    _check_common(plan_only)
    assert len(plan_only.data) == 2 and "Pocock-type" in plan_only.layout.title.subtitle.text
    far = charts.boundaries_figure(sq.sequential_boundaries(
        alpha=0.05, method="obrien-fleming", information_fractions=[0.001, 0.5, 1.0]))
    assert far.data[0].y[0] is None  # an infinite boundary is not drawn as a number
    assert "beyond the axis" in far.layout.title.subtitle.text


def test_novelty_figure_and_table():
    r = analyze_experiment(make_scenario("novelty_decay"), ExperimentConfig(
        primary=BIN, date_col="exposure_date"))
    fig = charts.novelty_figure(r.novelty, mode="dark")
    _check_common(fig, "dark")
    points, trend = fig.data
    assert len(points.x) == 14 and list(trend.y) == [r.novelty.fitted_start,
                                                     r.novelty.fitted_end]
    assert trend.line.color == DARK.series[1] and trend.line.width == 2
    assert "a warning, not proof" in fig.layout.title.subtitle.text
    assert any("per day" in a.text for a in fig.layout.annotations)
    assert not fig.layout.xaxis.zeroline and fig.layout.yaxis.rangemode == "tozero"
    rows = charts.novelty_rows(r.novelty)
    assert len(rows) == 14 and rows[0]["period"] == "2026-01-05"
    assert rows[0]["effect"] == r.novelty.periods[0].effect
    skipped = analyze_experiment(make_scenario("clean_win"), ExperimentConfig(
        primary=BIN, date_col="exposure_date", date_bin_days=7)).novelty
    empty = charts.novelty_figure(skipped)
    assert not empty.data and "usable period" in empty.layout.annotations[0].text
    assert charts.novelty_rows(skipped) == []


def test_segments_figure_is_labelled_exploratory():
    r = analyze_experiment(make_scenario("segment_heterogeneity"), ExperimentConfig(
        primary=BIN, segment_col="segment"))
    fig = charts.segments_figure(r.segments)
    _check_common(fig)
    assert fig.layout.title.text.startswith("Exploratory")
    assert "not findings" in fig.layout.title.subtitle.text
    assert _named(fig) == ["Pooled effect", "Significant after Holm correction",
                           "Not significant after correction"]
    significant = fig.data[1]
    assert list(significant.y) == ["mobile"] and significant.marker.symbol == "circle"
    assert fig.data[2].marker.symbol == "circle-open"  # shape, not colour, carries the flag
    assert significant.marker.color == fig.data[2].marker.color == LIGHT.series[0]
    rows = charts.segment_rows(r.segments)
    assert [row["segment"] for row in rows] == ["desktop", "mobile", "tablet"]
    assert rows[1]["significant after correction"] is True


def test_segment_rows_keep_the_segments_that_were_left_out():
    df = make_experiment(n=6000, lift=0.03)
    df.loc[df.index[:25], "segment"] = "smart-fridge"
    seg = analyze_experiment(df, ExperimentConfig(primary=BIN, segment_col="segment")).segments
    rows = charts.segment_rows(seg)
    assert rows[-1]["segment"] == "smart-fridge" and rows[-1]["effect"] is None
    assert "not analysed" in rows[-1]["note"]
    none = seg.model_copy(update={"segments": []})
    assert not charts.segments_figure(none).data


def test_p_value_histogram_highlights_only_the_rejections():
    counts = [100] + [50] * 19
    fig = charts.p_value_histogram(counts, 0.05)
    _check_common(fig)
    hit, rest = fig.data
    assert list(hit.y) == [100] and hit.marker.color == LIGHT.series[0]
    assert len(rest.y) == 19 and rest.marker.color == LIGHT.context
    assert fig.layout.barcornerradius == 4 and hit.width == pytest.approx(0.025)
    assert fig.layout.shapes[0].y0 == pytest.approx(1050 / 20)  # the flat no-effect level
    plain = charts.p_value_histogram(counts, 0.01)  # no bin lies entirely below alpha
    _check_common(plain)
    assert len(plain.data) == 1 and not plain.layout.showlegend
    with pytest.raises(ValueError):
        charts.p_value_histogram([5], 0.05)


def test_aa_and_coverage_figures():
    res = aa_check(make_experiment(n=3000), "converted", "binary", n_relabels=300)
    fig = charts.aa_figure(res)
    _check_common(fig)
    assert "calibrated" in fig.layout.title.text
    assert sum(sum(t.y) for t in fig.data) == 300
    lo = np.array([-1.0, 0.5, -0.2, -2.0])
    hi = np.array([1.0, 2.0, 0.3, -0.5])
    cov = charts.coverage_figure(lo, hi, 0.0, limit=3)
    _check_common(cov)
    covers, misses = cov.data
    assert covers.line.color == LIGHT.context and misses.line.color == LIGHT.series[0]
    assert covers.x == (1, 1, None, 3, 3, None) and misses.y == (0.5, 2.0, None)
    assert "2 intervals cover it, 1 miss" in cov.layout.title.subtitle.text
    for args in (([], []), ([0.0], [1.0, 2.0])):
        with pytest.raises(ValueError):
            charts.coverage_figure(*args, 0.0)


def test_rates_figure_uses_one_hue_and_labels_beyond_the_whiskers():
    fig = charts.rates_figure(["naive", "corrected"], [0.14, 0.05], [0.01, 0.005], 0.05)
    _check_common(fig)
    bars, labels = fig.data
    assert bars.marker.color == LIGHT.series[0] and bars.orientation == "h"
    assert list(labels.text) == ["  14.0%", "  5.0%"] and labels.x[0] == pytest.approx(0.16)
    assert labels.textfont.color == LIGHT.ink  # text never wears the series colour
    assert "alpha = 0.05" in fig.layout.title.subtitle.text
    for args in (([], [], []), (["a"], [0.1, 0.2], [0.1])):
        with pytest.raises(ValueError):
            charts.rates_figure(*args, 0.05)


def test_labels_from_the_data_cannot_inject_markup(report):
    hostile = '<a href="javascript:alert(1)">x</a><script>alert(1)</script>'
    df = make_experiment(n=4000, lift=0.04).rename(columns={"converted": hostile})
    df["segment"] = df["segment"].replace({"mobile": "<b>bold</b> " + "x" * 200})
    r = analyze_experiment(df, ExperimentConfig(
        primary=MetricSpec(column=hostile, type="binary"), segment_col="segment",
        date_col="exposure_date"))
    for fig in (charts.effects_figure(r), charts.segments_figure(r.segments),
                charts.novelty_figure(r.novelty)):
        spec = fig.to_json()
        assert "<script>" not in spec and "<a href" not in spec and "<b>bold" not in spec
    name = charts.segments_figure(r.segments).data[1].y[0]
    assert name.startswith("&lt;b&gt;bold") and len(name) <= 80
    assert charts.effects_rows(r)[0]["metric"] == hostile  # the table keeps the raw name
    assert "&lt;" in charts.empty_figure("<i>x</i>").layout.annotations[0].text
