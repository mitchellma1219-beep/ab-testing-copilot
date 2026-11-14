# Security

- **Input handling**: only `.csv` files are read, through `pandas.read_csv`. No pickle,
  `eval`, `exec`, shell calls or dynamic imports on user data. Row count is capped by
  `ABCOPILOT_MAX_ROWS` (default 5,000,000).
- **Resource bounds**: simulations cap `n_sims` at 1,000,000 and generate data in chunks of
  at most 4M cells; the bootstrap is chunked the same way.
- **Output**: `--out` writes exactly where the caller points it. Do not pass untrusted
  paths when wrapping the CLI in a service.
- **Secrets**: the project needs no credentials and makes no network calls.
- **Data**: bundled examples are synthetic. Do not commit real user data.

Not yet done: automated dependency and secret scanning in CI (bandit, pip-audit and
gitleaks were not available in the build environment). Report issues via GitHub issues.
