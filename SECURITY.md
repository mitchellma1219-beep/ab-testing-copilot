# Security

The tool reads local CSV files, computes statistics and writes reports. It needs no
credentials, opens no network connections and stores nothing between runs.

## Design

- **Input.** The CLI reads only `.csv` files, through `pandas.read_csv`, with a row cap
  (`ABCOPILOT_MAX_ROWS`, default 5,000,000). The dashboard reads an uploaded CSV in memory
  (100 MB and 2,000,000 rows at most) and writes nothing to disk. No pickle, `eval`,
  `exec`, shell call or dynamic import touches user data.
- **Resource bounds.** Simulations cap `n_sims` at 1,000,000 and generate data in chunks
  of at most 4M cells, as do the bootstrap and the A/A check (100 to 20,000
  re-labellings). Sequential designs are limited to 100 looks at least 0.001 apart in
  information fraction; the novelty check to 400 periods; segment analysis to 30 levels.
  The dashboard limits its simulations to 10,000 experiments of 50,000 units per arm.
- **Output.** Text that comes from the data (column names, labels, segment values, file
  names) is neutralised before it is rendered: `report.safe_text` escapes HTML tag
  openers, link and image syntax, code spans, table pipes and control characters in
  Markdown; `charts._label` HTML-escapes and truncates labels in figures; the demo pages
  use `html.escape`. Plan inputs with control characters or backticks are rejected, and
  the analysis command printed by the planner is shell-quoted. JSON output is strict (no
  `NaN` or `Infinity`).
- **Files.** `--out` writes exactly where the caller points it. Do not pass untrusted
  paths when wrapping the CLI in a service.
- **Data.** Bundled examples, demo assets and tests use synthetic data only. Do not commit
  real user data.
- **Dashboard.** It is a local, single-user tool without authentication. Do not expose it
  to a network you do not trust. Usage statistics are switched off in
  `.streamlit/config.toml`.

## Scans

Run on 2026-11-14 against the code of this pull request, and on every pull request by the
`audit` job in CI:

| Tool | Scope | Result |
|---|---|---|
| ruff, rule set `S` (flake8-bandit) | whole repository | No finding in shipped code. In `tests/` two rules are switched off, each for a stated reason: `S101` (pytest assertions) and `S603` (the tests start this repository's own scripts, the skill entry point and `streamlit run`, with fixed argument lists and no shell) |
| bandit 1.9.4, `bandit -r src app examples skills demo benchmarks` | 5,200 lines of code | No issues identified (0 low, 0 medium, 0 high); no `# nosec` anywhere |
| pip-audit 2.10.1, `pip-audit --skip-editable` in a clean virtual environment holding only `.[dev,ui]` | every installed dependency, runtime and development | No known vulnerabilities found |

Nothing had to be fixed or suppressed. pip-audit run against the shared build sandbox
instead of a clean environment reports vulnerabilities in packages that this project does
not depend on (for example pypdf and soupsieve); they are outside its dependency set, which
is why CI audits a fresh virtual environment.

Not run: a dedicated secret scanner (gitleaks or similar), dynamic testing of the
dashboard, and a review by a second person. A keyword search of the tracked files for
credentials and email addresses found no credential and one address, the GitHub no-reply
commit identity recorded in `PROJECT_STATE.md`.

## Reporting

Please open a GitHub issue for a vulnerability that needs no confidentiality, or use
GitHub's private vulnerability reporting for one that does.
