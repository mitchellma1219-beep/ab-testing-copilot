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
