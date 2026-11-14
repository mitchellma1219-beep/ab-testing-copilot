# Quality report — ab-testing-copilot 0.1.0

Environment: Python 3.13.18, numpy 2.5.3, scipy 1.18.1, pandas 3.0.5, pydantic 2.13.5 (Linux,
2 vCPU). Measured 2026-11-13. Every number below was produced by a command run in that
environment; nothing is estimated.

## Tests executed

| Layer | Tests | Result |
|---|---|---|
| Unit (`tests/unit`) | 46 | pass |
| Integration incl. CLI and skill script via subprocess (`tests/integration`) | 10 | pass |
| Adversarial (`tests/adversarial`) | 23 | pass |
| Statistical / Monte Carlo (`tests/statistical`) | 11 | pass |
| **Total** | **90** | **90 pass, 0 fail** (about 9 s) |

`ruff check .`: clean. `mypy` (strict, `src/`): no issues in 11 files.

## Cross-checks against trusted implementations

- Two-proportion z test: z² and p equal `scipy.stats.chi2_contingency(correction=False)` to 1e-10.
- Welch test: statistic, p and CI equal `scipy.stats.ttest_ind(equal_var=False)` to 1e-9.
- SRM p-value equals `scipy.stats.chisquare`.
- Benjamini-Hochberg equals `scipy.stats.false_discovery_control`; Holm and Bonferroni
  match hand-computed values.
- Sample size 10% -> 12%, alpha 0.05, power 0.8 gives 3,841 per arm (standard published value).
- Not cross-checked against statsmodels (not installable in the build environment).

## Monte Carlo validation (`abcopilot simulate --n-sims 5000 --seed 0`)

| Check | Estimate | Expected | Tolerance | Result |
|---|---|---|---|---|
| False-positive rate, normal, 1000/1000 | 0.0454 | 0.0500 | 0.0173 | pass |
| False-positive rate, binary 10%, 5000/5000 | 0.0524 | 0.0500 | 0.0223 | pass |
| False-positive rate, lognormal | 0.0494 | 0.0500 | 0.0273 | pass |
| False-positive rate, normal, 400/1600 | 0.0516 | 0.0500 | 0.0173 | pass |
| Power, normal, effect 0.125 SD | 0.7920 | 0.7982 | 0.0277 | pass |
| Power, binary 10% -> 12%, 3841/3841 | 0.8000 | 0.8000 | 0.0326 | pass |
| Power, binary, 2000/6000 | 0.6986 | 0.6870 | 0.0362 | pass |
| CI coverage, normal | 0.9494 | 0.9500 | 0.0173 | pass |
| CI coverage, binary | 0.9446 | 0.9500 | 0.0223 | pass |
| CI coverage, lognormal | 0.9458 | 0.9500 | 0.0273 | pass |
| Peeking, 5 looks, uncorrected (1000 sims) | 0.1430 | n/a | n/a | shows inflation |
| Peeking, 5 looks, Bonferroni (1000 sims) | 0.0400 | <= 0.0500 | 0.0276 | pass |
| FWER, 10 metrics, uncorrected | 0.3880 | 0.4013 | 0.0670 | pass |
| FWER, 10 metrics, Holm | 0.0410 | <= 0.0500 | 0.0276 | pass |
| FWER, 10 metrics, Bonferroni | 0.0540 | <= 0.0500 | 0.0276 | pass |
| CUPED variance ratio, rho 0.7 | 0.5110 | 0.5100 | 0.0865 | pass |

Tolerance = 4 x Monte Carlo SE + a fixed approximation slack (0.005 normal, 0.01 binary,
0.015 lognormal), defined in `simulation.py` before results were inspected. These
tolerances are wide enough that a miscalibration of about one percentage point would
not be caught at 5,000 simulations.

Decision engine on ground truth (`test_decision_engine_error_rates_on_ground_truth`):
200 null experiments and 100 experiments with a true +3 pp lift; the test asserts a wrong
call rate within binomial error of 5% on nulls and at least 90/100 `Ship` on true effects.

## Adversarial findings

| Case | Behaviour |
|---|---|
| SRM from dropping 15% of control non-converters (naive p < 0.001) | Inconclusive, evidence "invalid" |
| 8 duplicated rows per user | Refused: `unit_of_analysis` blocking; SRM computed on units |
| Users present in both arms | `contamination` blocking |
| One 5,000,000 revenue value in treatment | Outlier flagged, evidence "weak", not `Ship` |
| Missingness correlated with outcome in one arm | Blocking |
| Pre-period covariate shifted in one arm | `covariate_balance` blocking |
| Binary metric containing 7; string metric; one arm only; empty frame; inf | `ValueError` with a specific message |
| Empty file, binary garbage, wrong columns, unterminated quote, non-CSV, over row cap | CLI exit 1 with `error:` |

Defect found and fixed during testing: a pre-assignment covariate imbalance check that used
a fixed 0.1 SMD threshold would have missed impossible-under-randomisation imbalances in
large samples; it now uses 4 standard errors of the SMD. Design change during testing:
balanced missingness under 5% is noted without downgrading evidence; above 5% it
downgrades to "weak".

## Performance (single run each)

| Operation | Time | Peak additional memory (tracemalloc) |
|---|---|---|
| `analyze_experiment`, 10k rows, CUPED + 1 guardrail | 50 ms | 2 MB |
| same, 100k rows | 340 ms | 12 MB |
| same, 1M rows | 3.1 s | 117 MB |
| Bootstrap, 2,000 resamples x 100k per arm | 2.2 s | not measured |
| Validation suite, 5,000 sims | 2.4 s | not measured |

No baseline comparison against other libraries was run.

## Security

Manual review only: no eval/exec/pickle/subprocess on user input, CSV-only reads, row and
simulation caps, no network, no credentials. A keyword grep for secrets over the tree
found nothing. bandit, pip-audit and a dedicated secret scanner were **not** run.

## Not verified / not done

- **Line coverage is not measured** (coverage.py unavailable). The CI workflow enforces 85%
  but has never executed.
- **CI has never run**; the repository is not on GitHub yet.
- Python 3.11 and 3.12 are untested (only 3.13 was available).
- `pip install -e .` and the `abcopilot` console script are untested (no network for the
  build backend); the CLI was exercised through `python -m ab_testing_copilot` and the
  skill script.
- The skill was validated structurally (frontmatter, name = directory, script executes)
  but not loaded inside Claude Code.
- No dashboard, no group-sequential testing, no novelty-effect or HTE analysis, no
  ratio metrics, no hypothesis/metric-selection assistant.
- No independent reviewer pass (six-role review) has been run yet.
- ARCHITECTURE.md, CONTRIBUTING.md, PORTFOLIO.md are not written.

## Release recommendation

**Do not publish yet.** The statistical core is tested and behaves as documented, but the
release gates on coverage, CI, dashboard, security scanning and independent review are open.
