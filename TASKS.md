# Tasks

## ab-testing-copilot
- [x] design / analysis / diagnostics / decision / simulation modules
- [x] CLI, skill, synthetic data generator
- [x] unit, integration, adversarial, statistical tests; ruff; mypy
- [x] Coverage measured in CI; cross-checks against scipy and statsmodels
- [x] Clean-environment install and tests on Python 3.11 / 3.12 / 3.13 (GitHub Actions)
- [x] Group-sequential boundaries (Lan-DeMets), checked against published values
- [x] Ratio metrics (delta method), unit aggregation, A/A check
- [x] Novelty-effect diagnostic; exploratory segment analysis
- [x] `abcopilot plan` (refuses to guess), `abcopilot sequential`, `abcopilot aa`
- [x] Dashboard (setup, power calculator, simulation, results, diagnostics, decision, export)
- [x] ruff `S` rules, bandit, pip-audit; `audit` job in CI
- [x] `.claude/skills` link; SKILL.md covers the new commands
- [x] ARCHITECTURE.md, CONTRIBUTING.md, PORTFOLIO.md, demo assets, benchmarks
- [ ] Independent review by someone other than the author of the code (six-role review)
- [ ] Load the skill in Claude Code and run it on a real task
- [ ] Dedicated secret scanner (gitleaks) in CI
- [ ] Dashboard checked by a person in a browser beyond the automated tests and screenshots
- [ ] Futility boundaries, bias-adjusted estimates after early stopping, CUPED for ratio metrics
- [ ] Merge pull request #1 into `main`
- [ ] Owner decision: replace or keep the auto-generated initial commit before going public
- [ ] Release audit, then make the repository public and add topics

## auto-data-scientist
See TASKS.md in that repository (core done and green in CI; dashboard and release work open).

## agent-reliability-lab
- [ ] Everything (core buildable now: pydantic + jsonschema available)
