import json
import subprocess
import sys
from pathlib import Path

import pytest

from ab_testing_copilot.cli import main
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
)
from ab_testing_copilot.models import Decision
from ab_testing_copilot.report import render_markdown

ROOT = Path(__file__).resolve().parents[2]
BIN = MetricSpec(column="converted", type="binary")
REV = MetricSpec(column="revenue", type="continuous")
LOAD = GuardrailSpec(column="page_load_ms", type="continuous", higher_is_better=False)


def test_positive_effect_ships(make_df):
    r = analyze_experiment(make_df(lift=0.02), ExperimentConfig(
        primary=BIN, guardrails=[LOAD], unit_col="user_id"))
    assert r.decision is Decision.SHIP and r.evidence_quality == "strong"
    assert r.primary.ci_low <= 0.02 <= r.primary.ci_high
    assert r.guardrails[0].status == "pass"
    md = render_markdown(r)
    assert "Recommendation: Ship" in md and "page_load_ms" in md


def test_null_effect_is_inconclusive(make_df):
    r = analyze_experiment(make_df(lift=0.0), ExperimentConfig(primary=BIN, absolute_mde=0.02))
    assert r.decision is Decision.INCONCLUSIVE
    assert any("ruled out" in x for x in r.reasons)


def test_negative_effect_does_not_ship(make_df):
    r = analyze_experiment(make_df(lift=-0.02), ExperimentConfig(primary=BIN))
    assert r.decision is Decision.DO_NOT_SHIP


def test_guardrail_regression_blocks_ship(make_df):
    df = make_df(lift=0.02)
    df.loc[df.variant == "treatment", "page_load_ms"] += 100
    r = analyze_experiment(df, ExperimentConfig(primary=BIN, guardrails=[LOAD]))
    assert r.decision is Decision.DO_NOT_SHIP and r.guardrails[0].status == "fail"


def test_cuped_narrows_interval_and_recovers_truth(make_df):
    df = make_df(n=6000, rev_effect=0.6)
    raw = analyze_experiment(df, ExperimentConfig(primary=REV))
    adj = analyze_experiment(df, ExperimentConfig(primary=REV, covariate_col="pre_spend"))
    w_raw = raw.primary.ci_high - raw.primary.ci_low
    w_adj = adj.primary.ci_high - adj.primary.ci_low
    assert w_adj < 0.75 * w_raw
    assert adj.primary.ci_low <= 0.6 <= adj.primary.ci_high
    assert "CUPED" in adj.primary.method
    assert any(d.name == "covariate_balance" and d.passed for d in adj.diagnostics)


def test_peeking_penalty_widens_interval(make_df):
    df = make_df(lift=0.012, n=8000)
    one = analyze_experiment(df, ExperimentConfig(primary=BIN))
    five = analyze_experiment(df, ExperimentConfig(primary=BIN, n_looks=5))
    assert five.effective_alpha == pytest.approx(0.01)
    assert five.primary.ci_high - five.primary.ci_low > one.primary.ci_high - one.primary.ci_low
    assert five.evidence_quality == "weak"


def test_cli_end_to_end(make_df, tmp_path, capsys):
    path = tmp_path / "exp.csv"
    make_df(lift=0.02).to_csv(path, index=False)
    out = tmp_path / "report.json"
    code = main(["analyze", str(path), "--metric", "converted", "--metric-type", "binary",
                 "--guardrail", "page_load_ms:continuous:lower:0.02", "--unit-col", "user_id",
                 "--format", "json", "--out", str(out)])
    assert code == 0
    payload = json.loads(out.read_text())
    assert payload["decision"] == "Ship" and json.loads(capsys.readouterr().out) == payload

    assert main(["design", "--baseline", "0.1", "--mde", "0.2", "--relative",
                 "--daily-units", "1000"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["n_control"] == 3841 and d["duration_days"] == 8
    assert main(["design", "--metric-type", "continuous", "--std-dev", "10", "--mde", "1"]) == 0
    capsys.readouterr()
    assert main(["srm", "5000", "5400"]) == 2
    assert main(["srm", "5000", "5010"]) == 0


def test_cli_simulate_markdown_in_process(capsys):
    assert main(["simulate", "--n-sims", "500"]) == 0
    out = capsys.readouterr().out
    assert "false_positive_rate[normal]" in out and "| FAIL |" not in out
    assert out.count("| PASS |") == 22  # 24 checks, 2 of them informational


def test_cli_errors_are_clean(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "nope.csv"), "--metric", "x",
                 "--metric-type", "binary"]) == 1
    assert main(["design", "--mde", "0.1"]) == 1
    assert main(["design", "--metric-type", "continuous", "--mde", "1"]) == 1
    assert "error:" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["analyze", "x.csv", "--metric", "m", "--metric-type", "binary",
              "--guardrail", "bad"])


def test_skill_script_runs_from_checkout_without_install(make_df, tmp_path):
    script = ROOT / "skills" / "ab-testing-copilot" / "scripts" / "abcopilot.py"
    path = tmp_path / "exp.csv"
    make_df(lift=0.0, n=4000).to_csv(path, index=False)
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": ""}
    res = subprocess.run(
        [sys.executable, str(script), "analyze", str(path), "--metric", "revenue",
         "--metric-type", "continuous", "--covariate", "pre_spend"],
        capture_output=True, text=True, env=env, cwd=tmp_path, check=False)
    assert res.returncode == 0, res.stderr
    assert "Recommendation: Inconclusive" in res.stdout
    res = subprocess.run([sys.executable, str(script), "simulate", "--n-sims", "500", "--format",
                          "json"], capture_output=True, text=True, env=env, cwd=tmp_path,
                         check=False)
    assert res.returncode == 0, res.stderr
    assert len(json.loads(res.stdout)) == 24


def test_skill_frontmatter_is_valid():
    import yaml
    text = (ROOT / "skills" / "ab-testing-copilot" / "SKILL.md").read_text()
    _, fm, body = text.split("---", 2)
    meta = yaml.safe_load(fm)
    assert meta["name"] == "ab-testing-copilot" == (ROOT / "skills" / "ab-testing-copilot").name
    assert 0 < len(meta["description"]) <= 1024 and len(meta["name"]) <= 64
    assert len(body.splitlines()) < 500
