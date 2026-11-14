# Project state — three AI Skills (updated 2026-11-13)

## Blockers (need the owner)

1. **GitHub**: `gh auth status` reports the GH_TOKEN in this workspace is invalid, and no
   GitHub account is linked to Claude. Nothing has been published. No repository
   existence check was possible.
2. **Package installs are disabled** in this workspace (pypi.org does not resolve).
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
- Commit: see `git log` (local only; author email is a placeholder to replace before push).
- GitHub URL: none.

## Continue with

```bash
cd ab-testing-copilot
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
pytest --cov=ab_testing_copilot --cov-report=term-missing
ruff check . && mypy
python -m ab_testing_copilot simulate --n-sims 5000
```
