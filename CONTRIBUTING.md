# Contributing

## Setup

```bash
git clone <repo-url> && cd ab-testing-copilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,ui]"
```

Python 3.11 or newer. The `ui` extra (Streamlit, Plotly) is needed for the dashboard, the
chart builders, the demo and their tests; the rest runs on the `dev` extra alone, and the
UI tests are skipped when Streamlit or Plotly is missing.

## Checks to run before every push

```bash
ruff check .                                   # lint, including the bandit-style S rules
mypy                                           # strict, src/
pytest --cov=ab_testing_copilot --cov-fail-under=85
bandit -r src app examples skills demo benchmarks
pip-audit --skip-editable                      # in a clean virtual environment
```

CI runs the first three on Python 3.11, 3.12 and 3.13 and the last two in an `audit` job.
Do not use `pytest-xdist`: the Monte Carlo tests are seeded and sized for serial runs.

## Rules for statistical changes

Statistical correctness outranks every other goal. A change to a method needs all of:

1. **A reference** (paper, textbook or the documentation of an established package),
   cited in `skills/ab-testing-copilot/references/methodology.md`.
2. **A cross-check** against a published value or an independent implementation (scipy,
   statsmodels, a second algorithm). State where the published value comes from.
3. **A simulation** with a known ground truth. Fix the tolerance *before* the first run:
   `4 x Monte Carlo SE + slack` (0.005 normal data, 0.01 binary data), as in
   `simulation.py`. Derive power thresholds from the design, not from a trial run.
4. **Stated assumptions and limitations** in the methodology reference and, if the user
   must know them to read a result, in the report itself.

And never:

- loosen a tolerance, or change a seed, to make a failing statistical test pass. Fix the
  code; change the test only if its expectation was wrong, and say so in the commit;
- change a method, a threshold or the handling of an edge case in order to reach a
  conclusion on some dataset;
- let an exploratory result (segments, post-hoc cuts) feed the decision or the evidence
  rating;
- fill a missing input with a default in the planner;
- present a result of a check that was not run as "passed": use `assessed=False`.

## Rules for everything else

- **Synthetic data only.** No real user data, personal data, credentials or email
  addresses anywhere in the repository, including tests, fixtures and documentation.
- **Tests are deterministic and offline.** Fixed seeds, no network, no sleeping for luck.
- **Declare every dependency** in `pyproject.toml`, test-only ones included. A missing
  dev dependency broke CI once already.
- **Text that comes from data is untrusted.** Column names, labels and messages go
  through `report.safe_text` in Markdown and `charts._label` in figures.
- **Entry points stay thin.** A number that appears in the CLI, the skill or the dashboard
  is computed by the package. If the dashboard needs a new number, add a function to the
  package and test it there.
- **Charts** are pure functions in `charts.py` (data in, figure out) with a `*_rows` table
  twin; at most two series colours, one value axis, no status colour without a label.
- **`QUALITY_REPORT.md` holds measured numbers only.** Re-run the command and paste its
  output; do not edit a number by hand or carry one over from an earlier version.

## Adding a feature: checklist

- [ ] Function with type hints and a docstring that states the assumptions
- [ ] Input validation with specific `ValueError` messages
- [ ] Unit tests against an independent value; adversarial tests for misuse
- [ ] A simulation with a pre-set tolerance if the feature makes a statistical claim
- [ ] CLI option and `SKILL.md` row if users should reach it; methodology entry
- [ ] `CHANGELOG.md` entry; `QUALITY_REPORT.md` updated from fresh runs

## Commits and pull requests

Small commits with a subject in the imperative and a body that says what changed and why,
including any test expectation that was corrected. Work on a branch and open a pull
request; `main` is never pushed to directly and history is not rewritten.

## Regenerating generated files

```bash
python examples/generate_sample_data.py     # examples/*.csv
python demo/run_demo.py                     # demo/output/
python benchmarks/run_benchmarks.py --out benchmarks/results
python benchmarks/statistical_evidence.py   # the evidence tables in QUALITY_REPORT.md
```

Tests fail if the committed example files or demo reports no longer match their
generators.
