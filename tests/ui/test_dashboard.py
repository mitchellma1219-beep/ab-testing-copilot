"""The Streamlit dashboard, driven through the real script with Streamlit's AppTest.

One smoke test also starts ``streamlit run`` as a separate headless process on a free port,
polls its health endpoint and stops it.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("plotly")

from streamlit.testing.v1 import AppTest

from ab_testing_copilot import design
from ab_testing_copilot.synthetic import SCENARIOS, make_experiment, make_sessions

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app" / "streamlit_app.py"
TABS = ["Experiment setup", "Power calculator", "Simulation", "Statistical results",
        "Diagnostic warnings", "Decision report", "Export"]


def _app() -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _metric(at: AppTest, label: str) -> str:
    return next(m.value for m in at.metric if m.label == label)


def _charts(at: AppTest) -> list[dict]:
    return [json.loads(c.proto.spec) for c in at.get("plotly_chart")]


def _chart_titles(at: AppTest) -> list[str]:
    return [c["layout"]["title"]["text"] for c in _charts(at)]


def _banner(at: AppTest) -> str:
    return " ".join(e.value for e in [*at.success, *at.error, *at.warning]
                    if "Recommendation" in e.value)


def _select_scenario(at: AppTest, name: str) -> AppTest:
    at.sidebar.selectbox(key="scenario").set_value(name).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_default_page_has_every_section_and_works_offline():
    at = _app()
    assert [t.label for t in at.tabs] == TABS
    assert at.title[0].value == "A/B Testing Copilot"
    assert _banner(at) == "**Recommendation: Ship**"
    assert _metric(at, "Rows") == "20,000" and _metric(at, "Evidence quality") == "strong"
    assert _metric(at, "Absolute effect") == "+0.01195" and _metric(at, "Blocking") == "0"
    assert _metric(at, "Guardrails cleared") == "1 of 1"
    assert _chart_titles(at) == ["Power curve", "Effects with intervals",
                                 "Exploratory: effect by segment", "Treatment effect over time"]
    assert not at.error
    assert any("Synthetic data generated on this machine" in c.value for c in at.caption)
    assert any("hypothesis-generating only" in w.value for w in at.warning)


def test_export_offers_markdown_and_json_of_the_same_report():
    at = _app()
    buttons = at.get("download_button")
    assert [b.proto.label for b in buttons] == ["Download Markdown", "Download JSON"]
    raw_markdown, raw_json = at.code[0].value, at.code[1].value
    assert raw_markdown.startswith("# Decision report (Built-in scenario: Clean win)")
    assert "**Recommendation: Ship**" in raw_markdown and "## Diagnostics" in raw_markdown
    payload = json.loads(raw_json)
    assert payload["decision"] == "Ship" and payload["evidence_quality"] == "strong"
    assert payload["primary"]["metric"] == "converted"
    assert payload["segments"]["exploratory"] is True and payload["novelty"]["assessed"]
    assert f"{payload['primary']['absolute_effect']:+.5g}" in raw_markdown


@pytest.mark.parametrize("scenario, banner, quality", [
    ("no_effect", "Inconclusive", "strong"),
    ("guardrail_regression", "Do not ship", "strong"),
    ("sample_ratio_mismatch", "Inconclusive", "invalid"),
    ("novelty_decay", "Ship", "weak"),
    ("segment_heterogeneity", "Ship", "strong"),
])
def test_every_built_in_scenario_reaches_the_decision_its_truth_calls_for(scenario, banner,
                                                                          quality):
    at = _select_scenario(_app(), scenario)
    assert _banner(at) == f"**Recommendation: {banner}**"
    assert _metric(at, "Evidence quality") == quality
    assert any(SCENARIOS[scenario].truth == i.value for i in at.sidebar.info)
    text = " ".join(m.value for m in at.markdown)
    if scenario == "sample_ratio_mismatch":
        assert int(_metric(at, "Blocking")) >= 1 and "Sample ratio mismatch" in text
    if scenario == "novelty_decay":
        assert _metric(at, "Warnings") == "1" and "Possible novelty effect" in text
    if scenario == "guardrail_regression":
        assert "statistically significant regression" in text


def test_sequential_design_is_declared_through_the_setup_tab():
    at = _app()
    at.radio(key="looks_mode").set_value("Pre-registered sequential design").run()
    at.number_input(key="seq_planned").set_value(5).run()
    at.number_input(key="seq_current").set_value(2).run()
    assert not at.exception
    assert _metric(at, "Look") == "2 of 5"
    assert _metric(at, "Critical value (abs z)") == "3.3570"
    assert "Sequential stopping boundaries" in _chart_titles(at)
    # z = 2.77 at 20,000 units would ship at a fixed horizon; look 2 of 5 holds it back
    assert _banner(at) == "**Recommendation: Inconclusive**"
    assert any("Continue to the next planned look" in m.value for m in at.markdown)
    at.number_input(key="seq_current").set_value(9).run()  # a look outside the plan
    assert not at.exception and any("exceeds planned_looks" in e.value for e in at.error)
    assert any("Complete the experiment setup first" in i.value for i in at.info)


def test_unplanned_looks_apply_the_bonferroni_rule():
    at = _app()
    at.radio(key="looks_mode").set_value("Several looks without a plan").run()
    at.number_input(key="n_looks").set_value(5).run()
    assert not at.exception and _metric(at, "Confidence level") == "99.0%"
    assert _metric(at, "Evidence quality") == "weak" and _metric(at, "Warnings") == "1"


def test_setup_options_change_the_analysis():
    at = _app()
    at.selectbox(key="metric").set_value("revenue").run()
    assert at.selectbox(key="metric_type").value == "continuous"
    at.selectbox(key="covariate").set_value("pre_spend").run()
    at.selectbox(key="aa_relabels").set_value(300).run()
    at.checkbox(key="use_mde").set_value(True).run()
    assert not at.exception
    assert any("CUPED-adjusted Welch t test" in c.value for c in at.caption)
    assert any("A/A check" in t for t in _chart_titles(at))
    assert _banner(at) == "**Recommendation: Inconclusive**"  # revenue has no true effect
    at.selectbox(key="segment_col").set_value("(none)").run()
    at.selectbox(key="date_col").set_value("(none)").run()
    assert "Exploratory: effect by segment" not in _chart_titles(at)
    assert "Treatment effect over time" not in _chart_titles(at)


def test_wrong_setup_is_reported_not_raised():
    at = _app()
    at.selectbox(key="treatment").set_value("control").run()  # both arms the same label
    assert not at.exception
    assert any("The analysis could not run" in e.value for e in at.error)
    at.selectbox(key="treatment").set_value("treatment").run()
    at.selectbox(key="metric_type").set_value("continuous").run()
    at.selectbox(key="metric").set_value("page_load_ms").run()
    assert not at.exception and not at.error


def test_power_calculator_matches_the_design_module():
    at = _app()
    at.number_input(key="pw_mde").set_value(0.01).run()
    expected = design.sample_size_for_proportions(0.10, 0.01)
    assert _metric(at, "Control arm") == f"{expected.n_control:,}"
    assert _metric(at, "Total") == f"{expected.n_total:,}"
    assert _metric(at, "Days at the stated traffic") == str(
        design.duration_days(expected.n_total, 1500))
    curve = next(c for c in _charts(at) if c["layout"]["title"]["text"] == "Power curve")
    assert curve["data"][-1]["x"] == [expected.n_control]
    at.selectbox(key="pw_seq").set_value("pocock").run()
    assert not at.exception
    assert "Sequential stopping boundaries" in _chart_titles(at)
    assert int(_metric(at, "Maximum total with interim looks").replace(",", "")) > expected.n_total
    at.selectbox(key="pw_type").set_value("continuous").run()
    at.number_input(key="pw_std").set_value(10.0).run()
    at.number_input(key="pw_mde").set_value(1.0).run()
    assert _metric(at, "Control arm") == f"{design.sample_size_for_means(10, 1).n_control:,}"
    at.selectbox(key="pw_type").set_value("binary").run()
    at.number_input(key="pw_baseline").set_value(0.995).run()  # baseline + MDE above 1
    assert not at.exception and any("inside (0, 1)" in e.value for e in at.error)


def test_interactive_simulation_runs_on_demand():
    at = _app()
    assert any("run the simulation" in i.value for i in at.info)
    at.number_input(key="sim_n_sims").set_value(600)
    at.button[0].click().run()
    assert not at.exception
    rate = float(_metric(at, "False-positive rate").rstrip("%")) / 100
    assert abs(rate - 0.05) < 4 * (0.05 * 0.95 / 600) ** 0.5 + 0.005
    assert _metric(at, "Expected from theory") == "5.0%"
    titles = _chart_titles(at)
    assert "P-values across simulated experiments" in titles
    assert "Simulated confidence intervals" in titles
    at.number_input(key="sim_effect").set_value(0.2)
    at.button[0].click().run()
    assert float(_metric(at, "Power").rstrip("%")) > 95
    at.radio(key="sim_kind").set_value("Repeated looks at growing data").run()
    at.number_input(key="sim_n_sims").set_value(600)
    at.button[0].click().run()
    assert not at.exception
    rates = next(c for c in _charts(at)
                 if c["layout"]["title"]["text"] == "False-positive rate by analysis rule")
    naive, bonferroni, obf, pocock = rates["data"][0]["x"]
    assert naive > 0.09 and max(bonferroni, obf, pocock) < 0.09


def test_uploaded_csv_is_analysed_and_hostile_names_are_neutralised():
    at = _app()
    at.sidebar.radio(key="source").set_value("Upload a CSV").run()
    assert any("Upload a CSV in the sidebar" in i.value for i in at.info)
    df = make_experiment(n=3000, lift=0.05).rename(columns={
        "converted": "<script>alert(1)</script>", "segment": "seg|$x$](http://evil)"})
    at.sidebar.file_uploader(key="upload").upload("exp.csv", df.to_csv(index=False).encode(),
                                                  "text/csv").run()
    assert not at.exception
    at.selectbox(key="metric").set_value("<script>alert(1)</script>").run()
    at.selectbox(key="segment_col").set_value("seg|$x$](http://evil)").run()
    assert not at.exception and not at.error
    assert _banner(at) == "**Recommendation: Ship**" and _metric(at, "Rows") == "3,000"
    rendered = [m.value for m in at.markdown]
    assert not any("<script>" in v.replace("\\<script>", "") for v in rendered)
    assert not any("](http" in v for v in rendered)
    assert all("<script>" not in json.dumps(c) for c in _charts(at))


def test_unusable_uploads_are_explained():
    at = _app()
    at.sidebar.radio(key="source").set_value("Upload a CSV").run()
    upload = at.sidebar.file_uploader(key="upload")
    upload.upload("bad.csv", b"\x00\xff\xfe garbage \x80", "text/csv").run()
    assert not at.exception and at.error
    at.sidebar.file_uploader(key="upload").upload("one.csv", b"only\n1\n2\n", "text/csv").run()
    assert not at.exception
    assert any("needs a variant column" in e.value for e in at.error)
    sessions = make_sessions(n_users=300).to_csv(index=False).encode()
    at.sidebar.file_uploader(key="upload").upload("sessions.csv", sessions, "text/csv").run()
    at.selectbox(key="metric").set_value("clicks").run()
    assert not at.exception
    assert _metric(at, "Evidence quality") == "invalid"  # several rows per user are refused


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_streamlit_server_starts_headless_and_reports_healthy():
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
           "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(APP), "--server.headless", "true",
         "--server.port", str(port), "--server.address", "127.0.0.1",
         "--server.fileWatcherType", "none"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never via a proxy
    try:
        body, deadline = "", time.monotonic() + 120
        while time.monotonic() < deadline and body != "ok":
            assert proc.poll() is None, f"streamlit exited early:\n{proc.stdout.read()}"
            try:
                with opener.open(f"{url}/_stcore/health", timeout=5) as response:
                    body = response.read().decode().strip()
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.5)
        assert body == "ok", "the health endpoint never answered ok"
        with opener.open(url, timeout=10) as response:
            assert response.status == 200 and b"<title>Streamlit</title>" in response.read()
        assert proc.poll() is None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=20)
    assert proc.poll() is not None
