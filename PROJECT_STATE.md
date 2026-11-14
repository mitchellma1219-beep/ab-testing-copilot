# Project state — three AI Skills (updated 2026-11-13)

## Blockers (need the owner)

1. **GitHub connection (in progress, 2026-11-13 21:15 PT)**: GitHub account `mitchellma1219-beep`
   (personal). Three **private** repos were created in the browser with an auto-generated
   README commit: `auto-data-scientist` (b5aca74), `ab-testing-copilot` (2e9f9f6),
   `agent-reliability-lab` (d22393f). Still needed from the owner: install/authorize the
   Claude GitHub App on these three repos and connect GitHub in Claude. Until then the
   session cannot clone or push. Nothing has been pushed yet.
   - The auto-generated initial commits carry the owner's Gmail address as author. Decide
     before making the repos public whether to replace them (force-push, needs approval).
   - Commit identity for our commits: `Mitchell Ma <325205137+mitchellma1219-beep@users.noreply.github.com>`.
2. **Package installs are disabled** in this workspace (pypi.org does not resolve). The
   owner needs to turn on "Allow network egress" (Settings > Capabilities); a new chat may
   be required for it to take effect.
   Missing: duckdb, statsmodels, streamlit, plotly, pyarrow, polars, coverage/pytest-cov,
   bandit, pip-audit, hypothesis. This blocks Milestone A (DuckDB is its required engine),
   every dashboard, coverage measurement and security scanners.

## Milestone order

Milestone A (auto-data-scientist) is blocked by (2), so work started on the independent
parts of Milestone B, as the directive allows.

| Project | State |
|---|---|
| auto-data-scientist | Not started (blocked: DuckDB, pyarrow, Streamlit unavailable) |
| ab-testing-copilot | Core engine, CLI, skill, 90 passing tests, local git commit. Not published. |
| agent-reliability-lab | Not started (core is buildable with what is installed) |

## ab-testing-copilot

- Path: `/home/claude/workspace/ab-testing-copilot` (cloud workspace; a zip was sent in chat)
- Verified: `pytest` 90 passed; `ruff check .` clean; `mypy` strict clean. See QUALITY_REPORT.md.
- Commit: see `git log` (local only, authored with the GitHub noreply address).
- GitHub URL: https://github.com/mitchellma1219-beep/ab-testing-copilot (private, README only so far).

## Continue with

```bash
cd ab-testing-copilot
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
pytest --cov=ab_testing_copilot --cov-report=term-missing
ruff check . && mypy
python -m ab_testing_copilot simulate --n-sims 5000
```
