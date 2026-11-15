"""The helper scripts that ship with the repository: examples and benchmarks."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from ab_testing_copilot.synthetic import make_experiment, make_sessions

ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_example_files_match_the_generator(tmp_path):
    experiment = pd.read_csv(ROOT / "examples" / "sample_experiment.csv")
    pd.testing.assert_frame_equal(experiment, make_experiment(seed=7))
    sessions = pd.read_csv(ROOT / "examples" / "sample_sessions.csv")
    pd.testing.assert_frame_equal(sessions, make_sessions(n_users=2000, ctr_lift=0.01, seed=7))
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": ""}
    res = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "generate_sample_data.py"), "--out-dir",
         str(tmp_path)], capture_output=True, text=True, env=env, cwd=tmp_path, check=False)
    assert res.returncode == 0, res.stderr
    for name in ("sample_experiment.csv", "sample_sessions.csv"):
        assert (tmp_path / name).read_bytes() == (ROOT / "examples" / name).read_bytes()


def test_benchmarks_run_in_quick_mode(tmp_path, capsys):
    bench = _load(ROOT / "benchmarks" / "run_benchmarks.py")
    assert bench.main(["--quick", "--repeats", "1", "--out", str(tmp_path)]) == 0
    table = capsys.readouterr().out
    payload = json.loads((tmp_path / "benchmarks.json").read_text())
    assert payload["quick"] is True and payload["repeats"] == 1
    assert payload["environment"]["cpu_count"] >= 1
    names = [r["name"] for r in payload["results"]]
    assert len(names) == 11 and all(r["best_s"] > 0 for r in payload["results"])
    for fragment in ("analyze_experiment", "sequential_boundaries", "aa_check",
                     "aggregate_to_units", "ratio metric", "run_validation_suite"):
        assert any(fragment in n for n in names)
    assert (tmp_path / "benchmarks.md").read_text() == table
    assert table.count("\n| ") == 11 and "run(s) per operation" in table  # one row each


def test_demo_script_regenerates_the_committed_assets(tmp_path):
    import pytest

    pytest.importorskip("plotly")
    demo = _load(ROOT / "demo" / "run_demo.py")
    written = demo.build(tmp_path)
    committed = ROOT / "demo" / "output"
    names = sorted(str(p.relative_to(tmp_path)) for p in written)
    assert names == sorted(str(p.relative_to(committed)) for p in committed.rglob("*")
                           if p.is_file())
    verdicts = {
        "report_clean_win.md": ("Ship", "strong"),
        "report_sample_ratio_mismatch.md": ("Inconclusive", "invalid"),
        "report_novelty_decay.md": ("Ship", "weak"),
        "report_segment_heterogeneity.md": ("Ship", "strong"),
        "report_sequential_look2.md": ("Inconclusive", "strong"),
        "report_sequential_look3.md": ("Ship", "strong"),
        "report_ratio_metric.md": ("Ship", "strong"),
    }
    for name, (decision, quality) in verdicts.items():
        for folder in (tmp_path, committed):  # the regenerated file and the committed one
            head = (folder / name).read_text().splitlines()[:4]
            assert head[2] == f"**Recommendation: {decision}**  ", (folder, name)
            assert head[3] == f"Evidence quality: **{quality}**  ", (folder, name)
    payload = json.loads((tmp_path / "report_clean_win.json").read_text())
    assert payload["decision"] == "Ship" and payload["aa_check"]["verdict"] == "calibrated"
    plan = (tmp_path / "experiment_plan.md").read_text()
    assert "## Pre-registration checklist" in plan and "## Looks and boundaries" in plan
    suite = (tmp_path / "validation_suite.md").read_text()
    assert suite.count("| PASS |") == 22 and "| FAIL |" not in suite
    index = (tmp_path / "charts" / "index.html").read_text()
    pages = sorted(p.name for p in (tmp_path / "charts").glob("*.html"))
    assert len(pages) == 10 and all(f'href="{p}"' in index for p in pages if p != "index.html")
    for name in pages:
        text = (tmp_path / "charts" / name).read_text()
        assert "http://" not in text and "https://cdn" not in text  # nothing fetched online
        if name != "index.html":
            assert '<script src="plotly.min.js"></script>' in text
            assert "View as table" in text and "<table>" in text
    assert (tmp_path / "charts" / "plotly.min.js").stat().st_size > 1_000_000
