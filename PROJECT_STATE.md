# Project state — three AI Skills (updated 2026-11-13, 21:30 PT)

## GitHub

- Account: `mitchellma1219-beep` (personal). Claude GitHub App installed on exactly three
  repositories and linked to Claude (installation 181814682).
- All three repositories are **private** until their release gates are met:

| Repository | State |
|---|---|
| https://github.com/mitchellma1219-beep/ab-testing-copilot | `main`: auto-generated README. Work is on `feat/core-engine`, draft pull request #1, CI green. |
| https://github.com/mitchellma1219-beep/auto-data-scientist | `main`: auto-generated README only. Not started. |
| https://github.com/mitchellma1219-beep/agent-reliability-lab | `main`: auto-generated README only. Not started. |

- Commit identity: `Mitchell Ma <325205137+mitchellma1219-beep@users.noreply.github.com>`.
- Open decision for the owner: the auto-generated initial commit in each repository carries
  the owner's personal email as author. Before a repository is made public, decide whether to
  replace that commit (force-push, needs explicit approval) or keep it.

## Blocker (needs the owner)

**Package installs are still disabled in the build sandbox** (pypi.org does not resolve).
The owner needs to turn on "Use the internet while making files" in Settings > Capabilities
(under "Create and edit files"); a new chat may be needed for it to take effect.
Missing locally: duckdb, statsmodels, streamlit, plotly, pyarrow, polars, pytest-cov, bandit,
pip-audit, hypothesis. This blocks Milestone A (DuckDB is its required engine) and every
dashboard. GitHub Actions is not affected and is currently the only place where the full
dev dependency set runs.

## Milestones

Milestone A (auto-data-scientist) is blocked by the install restriction, so work started on
the independent parts of Milestone B, as the directive allows.

| Project | State |
|---|---|
| auto-data-scientist | Not started (blocked: DuckDB, pyarrow, Streamlit unavailable locally) |
| ab-testing-copilot | Core engine, CLI, skill. 99 tests green in CI on Python 3.11/3.12/3.13, coverage 97.74%. Dashboard and release docs open. Not released. |
| agent-reliability-lab | Not started (core is buildable with what is installed locally) |

## ab-testing-copilot evidence

- Pull request: https://github.com/mitchellma1219-beep/ab-testing-copilot/pull/1 (draft)
- CI run 43561369486: ruff clean, mypy strict clean, 99 passed on 3.11.18 / 3.12.16 / 3.13.18,
  line coverage 97.74%. The first run (43561092763) failed on a missing PyYAML dev
  dependency, which was fixed.
- Details: QUALITY_REPORT.md. Remaining work: TASKS.md.

## Continue with

```bash
git clone https://github.com/mitchellma1219-beep/ab-testing-copilot && cd ab-testing-copilot
git checkout feat/core-engine
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
pytest --cov=ab_testing_copilot --cov-report=term-missing
ruff check . && mypy
abcopilot simulate --n-sims 5000
```
