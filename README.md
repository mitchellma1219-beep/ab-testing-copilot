# A/B Testing Copilot

A statistics-first toolkit and Agent Skill for designing, diagnosing, analysing and deciding
on randomized experiments. It prefers "Inconclusive" over a confident wrong answer.

> Status: v0.1.0, core engine + CLI + skill. The dashboard is not built yet. See
> [QUALITY_REPORT.md](QUALITY_REPORT.md) for what has and has not been verified.

## What it does

- **Design**: sample size, power, MDE and duration for binary and continuous metrics,
  with unequal allocation.
- **Diagnostics**: sample ratio mismatch, contaminated units, wrong unit of analysis,
  differential missing data, outlier dominance, covariate balance, peeking.
- **Analysis**: two-proportion z test, Welch t test, absolute and relative effects with
  intervals, percentile bootstrap, CUPED, Bonferroni / Holm / Benjamini-Hochberg.
- **Decision**: `Ship`, `Do not ship` or `Inconclusive`, with reasons, guardrail status
  and an evidence-quality rating.
- **Simulation**: a seeded Monte Carlo suite that checks false-positive rate, power, CI
  coverage, peeking inflation, family-wise error and CUPED against theory.

## Install

```bash
git clone <repo-url> && cd ab-testing-copilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Requires Python 3.11+. Runtime dependencies: numpy, scipy, pandas, pydantic.

## Use

```bash
python examples/generate_sample_data.py          # synthetic data, true lift = +1.5 pp

abcopilot design --baseline 0.10 --mde 0.02 --daily-units 1500
abcopilot analyze examples/sample_experiment.csv \
    --metric converted --metric-type binary \
    --guardrail page_load_ms:continuous:lower:0.02 \
    --unit-col user_id --mde 0.015
abcopilot srm 5000 5400
abcopilot simulate --n-sims 5000 --seed 0
```

Output of the `analyze` command above (abridged):

```
Recommendation: Ship        Evidence quality: strong
converted  0.0981 -> 0.1100   +0.0119 [+0.0035, +0.0204]   +12.18% [+3.04%, +21.32%]   p = 0.0056
page_load_ms guardrail: PASS (harm larger than the 2% margin is ruled out)
sample_ratio_mismatch: OK (p = 0.235)
```

Python API:

```python
import pandas as pd
from ab_testing_copilot import ExperimentConfig, analyze_experiment
from ab_testing_copilot.experiment import MetricSpec

report = analyze_experiment(
    pd.read_csv("examples/sample_experiment.csv"),
    ExperimentConfig(primary=MetricSpec(column="revenue", type="continuous"),
                     unit_col="user_id", covariate_col="pre_spend"),
)
print(report.decision, report.primary.ci_low, report.primary.ci_high)
```

## Agent Skill

`skills/ab-testing-copilot/` follows the Agent Skills layout (`SKILL.md` with `name` and
`description` frontmatter, `scripts/`, `references/`). To use it in Claude Code, copy or
symlink the folder into `.claude/skills/` (project) or `~/.claude/skills/` (personal).
The skill script works from a checkout without installing the package.

## Architecture

```
CSV / counts ──> experiment.py ──> diagnostics.py ──┐
                      │                             ├──> decision.py ──> report.py / JSON
                      └──────────> analysis.py ─────┘
design.py (sample size, power)        simulation.py (Monte Carlo, reuses analysis cores)
cli.py and skills/.../abcopilot.py are thin entry points over the same functions.
```

## Testing

```bash
pytest            # 90 tests: unit, integration, adversarial, statistical
ruff check . && mypy
```

Methods and limitations: [skills/ab-testing-copilot/references/methodology.md](skills/ab-testing-copilot/references/methodology.md).
Security notes: [SECURITY.md](SECURITY.md). All sample data is synthetic.

## License

MIT
