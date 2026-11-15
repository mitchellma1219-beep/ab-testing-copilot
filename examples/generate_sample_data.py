#!/usr/bin/env python3
"""Write the synthetic example files (known ground truth, no real users).

    python examples/generate_sample_data.py

* ``sample_experiment.csv``: one row per user. True conversion lift +1.5 pp, no effect on
  revenue or page load, constant over time and across segments.
* ``sample_sessions.csv``: one row per session, several per user, users randomised. True
  click-through lift +1 pp on ``sum(clicks) / sum(impressions)``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from ab_testing_copilot.synthetic import make_experiment, make_sessions
except ModuleNotFoundError:  # running from a repository checkout without installation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from ab_testing_copilot.synthetic import make_experiment, make_sessions

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).parent)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    experiment = a.out_dir / "sample_experiment.csv"
    make_experiment(seed=a.seed).to_csv(experiment, index=False)
    sessions = a.out_dir / "sample_sessions.csv"
    make_sessions(n_users=2000, ctr_lift=0.01, seed=a.seed).to_csv(sessions, index=False)
    print(f"wrote {experiment} and {sessions}")
