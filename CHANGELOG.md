# Changelog

## 0.1.0 (unreleased)

Second milestone (2026-11-14):

- **Group-sequential testing.** Lan-DeMets alpha-spending boundaries (O'Brien-Fleming type
  and Pocock type) for up to 100 planned looks, computed by numerical integration, with
  exit probabilities, power, expected stopping point and the sample-size inflation factor.
  `ExperimentConfig.sequential` declares a pre-registered design (method, planned looks,
  current look, optional planned sample size); the primary metric and the guardrails are
  then judged at that look's critical value. Unplanned looks keep the Bonferroni rule.
- **Ratio metrics and the unit of analysis.** `compare_ratios` (delta method on unit-level
  sums), `aggregate_to_units`, and `--aggregate` / `--denominator` on the CLI.
- **A/A check.** `aa_check` re-labels units at random and compares the empirical
  false-positive rate with alpha; an inflated rate is a blocking diagnostic.
- **Novelty-effect diagnostic.** Weighted trend of per-period effects, reported as a
  warning with its evidence.
- **Exploratory segment analysis.** Per-segment effects, adjusted p-values, simultaneous
  intervals and Cochran's Q. Never an input to the decision.
- **`abcopilot plan`.** An experiment plan for pre-registration that lists missing inputs
  instead of guessing them. Also new: `abcopilot sequential` and `abcopilot aa`.
- **Dashboard.** `app/streamlit_app.py` with seven sections and Plotly charts from the
  pure `charts.py`; a `ui` extra; built-in synthetic scenarios.
- **Security.** ruff `S` rules, bandit and pip-audit locally and in a CI `audit` job.
  Reports and charts escape text that comes from the data.
- **Agent Skill.** `.claude/skills/ab-testing-copilot` links to the skill; `SKILL.md`
  covers the new commands.
- **Documentation and demo.** `ARCHITECTURE.md`, `CONTRIBUTING.md`, `PORTFOLIO.md`,
  `demo/` (script, sample reports, standalone charts, screenshots), `benchmarks/`.

Behaviour changes to existing features:

- With unplanned looks (`n_looks > 1`), a guardrail now counts as passed only if harm
  beyond its margin is ruled out at the Bonferroni level. A regression is still flagged at
  the unadjusted level, as before. This can turn a former "pass" into "uncertain"; it
  never makes a result more favourable.
- Critical values are computed with the survival function (`isf`) so that the very small
  nominal levels of early sequential looks keep finite intervals. Results for ordinary
  alphas are unchanged.
- Metric values so large that a variance overflows now raise `ValueError` instead of
  producing `NaN` statistics.
- The CLI exits quietly when its output pipe is closed early.
- `examples/sample_experiment.csv` keeps its six original columns unchanged and gains
  `exposure_date` and `segment`; `examples/sample_sessions.csv` is new.
- The Monte Carlo validation suite grew from 16 to 24 checks. The three tests that pin
  its size were updated accordingly (16 -> 24 results, 15 -> 22 PASS rows).

Defects found by the new tests and fixed before release:

- A segment column with mixed label types (for example `1` and `"one"`) raised
  `TypeError`.
- Dates far apart (years 0001 and 9999) overflowed the day arithmetic of the novelty
  check.
- The first version of the novelty check called a trend that crosses zero and continues
  on the other side a "decay". It is now reported as a reversal, for information.
- The planner accepted a binary baseline outside (0, 1) until sample-size time.
- In the dashboard, choosing another primary metric left the metric type of the previous
  one selected.
- The built-in sample ratio mismatch scenario described its artefact as an apparent win.
  Losing non-converting control users inflates the control rate, so the artefact is an
  apparent loss. The description, the demo text and the screenshot were corrected and a
  test now ties the description to the data; the data did not change.

First milestone (2026-11-13):

- Design, analysis, diagnostics, decision and Monte Carlo modules.
- `abcopilot` CLI and `ab-testing-copilot` Agent Skill.
- 99 tests (unit, integration, adversarial, statistical), including cross-checks against
  scipy and statsmodels.
- GitHub Actions CI on Python 3.11, 3.12 and 3.13 (lint, types, tests, coverage gate).
