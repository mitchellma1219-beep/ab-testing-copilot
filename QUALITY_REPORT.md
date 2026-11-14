# Quality report: ab-testing-copilot 0.1.0 (unreleased)

Every number in this report was produced by a command that was run on 2026-11-14 (UTC)
against the code of pull request #1. Nothing is estimated or carried over from an earlier
version of this report. Where a claim rests on something that was not checked, it says so.
This report does not claim that the software is correct; it records what was tested and
what was found.

## Environments

- **Clean virtual environment** on the build machine (Linux, 2 virtual CPUs shared with
  other jobs), created with `pip install -e ".[dev,ui]"`: Python 3.13.18, numpy 2.5.4,
  scipy 1.18.1, pandas 3.1.1, pydantic 2.14.3, streamlit 1.67.0, plotly 7.1.0,
  statsmodels 0.15.0, pytest 9.2.0, pytest-cov 7.1.0, ruff 0.17.5, mypy 2.4.1,
  bandit 1.9.4, pip-audit 2.10.1.
- **GitHub Actions** (`ubuntu-latest`, the same install command): Python 3.11.18, 3.12.16
  and 3.13.18. The install logs of the Python 3.13 test job and of the audit job list the
  same package versions as above.

## Tests executed

| Layer | Tests | What it checks |
|---|---|---|
| Unit (`tests/unit`), 11 of them statsmodels cross-checks | 279 | Formulas against published values, scipy, statsmodels and hand calculations; input validation |
| Integration (`tests/integration`) | 31 | The pipeline, the CLI, the skill script, the example files, the demo script and the benchmark script end to end |
| Adversarial (`tests/adversarial`) | 66 | Misuse and hostile input are refused or flagged |
| Statistical (`tests/statistical`) | 41 | Seeded Monte Carlo against tolerances fixed in advance |
| UI (`tests/ui`) | 30 | Chart builders; the dashboard script driven by `streamlit.testing.v1.AppTest`; one headless `streamlit run` on a free port polled at `/_stcore/health` |
| **Total** | **447** | |

| Where | Command | Result |
|---|---|---|
| Clean virtual environment | `pytest --cov=ab_testing_copilot --cov-report=term-missing --cov-fail-under=85` | 447 passed in 126.10 s |
| CI run 43579387120, Python 3.11 | same | 447 passed in 150.65 s |
| CI run 43579387120, Python 3.12 | same | 447 passed in 112.24 s |
| CI run 43579387120, Python 3.13 | same | 447 passed in 150.32 s |
| All four | `ruff check .` | All checks passed |
| All four | `mypy` (strict, `src/`) | no issues found in 19 source files |

No test is skipped or marked as an expected failure. The suite is seeded and needs no
network.

## Coverage (pytest-cov, line coverage)

Identical in the clean virtual environment and on all three CI Python versions.

| Module | Statements | Missed | Cover |
|---|---|---|---|
| `__init__.py` | 11 | 0 | 100% |
| `__main__.py` | 2 | 0 | 100% |
| `aa.py` | 123 | 0 | 100% |
| `analysis.py` | 174 | 0 | 100% |
| `charts.py` | 214 | 0 | 100% |
| `cli.py` | 283 | 1 | 99% |
| `decision.py` | 98 | 0 | 100% |
| `design.py` | 102 | 0 | 100% |
| `diagnostics.py` | 67 | 0 | 100% |
| `experiment.py` | 298 | 0 | 100% |
| `heterogeneity.py` | 52 | 0 | 100% |
| `models.py` | 175 | 0 | 100% |
| `novelty.py` | 82 | 0 | 100% |
| `plan.py` | 196 | 0 | 100% |
| `report.py` | 60 | 0 | 100% |
| `sequential.py` | 262 | 0 | 100% |
| `simulation.py` | 201 | 0 | 100% |
| `synthetic.py` | 62 | 0 | 100% |
| `units.py` | 58 | 0 | 100% |
| **Total** | **2,520** | **1** | **99.96%** |

The CI gate is 85%. The missed line is the `raise SystemExit(main())` guard of `cli.py`,
which only runs in a subprocess. Coverage is measured for the package only: the dashboard
script, the skill script, the demo and the benchmarks are exercised by tests but not
counted. Line coverage says that a line ran, not that its result is right; the sections
below are the evidence for that.

## CI history (GitHub Actions, pull request #1)

| Run | Commit | Result | Notes |
|---|---|---|---|
| 43561092763 | c91f021 | failed | A clean environment exposed a missing dev dependency (PyYAML). Fixed in the next commit |
| 43561369486 | f5db2a1 | passed | 99 tests |
| 43561578608 | 0c22a73 | passed | Smoke test of the installed console script added |
| 43565395563 | e41010b | passed | 99 tests, coverage 97.74%. Starting point of the second milestone |
| 43573374245 | 85ebc3b | passed | 236 tests, coverage 90.88% (features wired in, their tests still to come) |
| 43575791233 | 0c67e9d | passed | 396 tests, coverage 98.28%; first run with the `audit` job |
| 43576919276 | c416a53 | passed | 444 tests, coverage 99.96% |
| 43577599275 | 6e1fb97 | passed | 444 tests, coverage 99.96% |
| 43579387120 | ce8cd12 | passed | 447 tests, coverage 99.96%; `audit` job passed. Last run on a commit that changes package code or tests |

Commits after ce8cd12 change documentation, the recorded benchmark results and one
evidence script only. Their runs are listed on the pull request.

## Group-sequential boundaries against published values

`python benchmarks/statistical_evidence.py` (first table). The same comparisons are
asserted in `tests/unit/test_sequential.py`.

| Quantity | Computed | Published or design value |
|---|---|---|
| O'Brien-Fleming type, 5 looks | 4.876885, 3.357012, 2.680280, 2.289817, 2.031032 | 4.8769, 3.3570, 2.6803, 2.2898, 2.0310 (Stata); 3.3569 at look 2 (NCSS) |
| O'Brien-Fleming type, 4 looks | 4.332634, 2.963132, 2.359044, 2.014090 | 4.333, 2.963, 2.359, 2.014 (gsDesign) |
| Pocock type, 4 looks | 2.368328, 2.367524, 2.358168, 2.350030 | 2.368328, 2.367524, 2.358168, 2.350030 (gsDesign) |
| Kim-DeMets t^3, 3 equal looks | 3.1130, 2.4619, 2.0087 | 3.1130, 2.4619, 2.0087 (Stata) |
| Kim-DeMets t^3, looks at 1/3, 1/2, 2/3, 1 | 3.1130, 2.7889, 2.5133, 2.0120 | 3.1130, 2.7889, 2.5133, 2.0120 (Stata) |
| Inflation factor, O'Brien-Fleming type, 5 looks, power 0.8 | 1.024718 | 1.0247 (Stata) |
| Overall alpha of the classical Pocock constant 2.413, 5 looks | 0.050022 | 0.05 |
| Overall alpha of the classical O'Brien-Fleming constant 2.040, 5 looks | 0.050009 | 0.05 |
| Power of classical Pocock at sample-size ratio 1.229 | 0.8003 | 0.8 |
| Power of classical O'Brien-Fleming at sample-size ratio 1.028 | 0.7999 | 0.8 |
| Overall error of a 5% test repeated at 2, 3, 4, 5, 10 looks | 0.0831, 0.1073, 0.1262, 0.1417, 0.1934 | 0.083, 0.107, 0.126, 0.142, 0.193 |
| Overall alpha by scipy multivariate normal integration, O'Brien-Fleming type, 4 looks | 0.05000000 | 0.05 (design value) |
| Overall alpha by scipy multivariate normal integration, Pocock type, 4 looks | 0.05000002 | 0.05 (design value) |

Test tolerances: 5e-5 for values printed to four decimals (half a unit in the last digit),
1e-6 for the six-decimal gsDesign values and 5e-4 for the three-decimal ones. The quadrature
at its default resolution agrees with a three times finer one to 1e-9.

Where the published values come from, and how far each was checked:

- **Read from the source during this work:** the Stata `gsbounds` manual entry (examples 7
  to 9), the NCSS PASS documentation of group-sequential tests, the gsDesign technical
  manual (spending functions chapter), and DeMets and Lan (1994) for the constants 2.41
  and 2.04.
- **Checked against a secondary source:** the three-decimal constants 2.413 and 2.040 and
  the repeated-testing values are attributed in the tests to Jennison and Turnbull (2000)
  and to Armitage, McPherson and Rowe (1969). They were compared with University of
  Washington SISCER lecture slides that print the same values
  (<https://si.biostat.washington.edu/sites/default/files/modules/SISCER_Mod13_Day2.pdf>),
  not with the book or the paper.
- **Not checked against any source:** the sample-size ratios 1.229 and 1.028 were quoted
  from memory of Jennison and Turnbull (2000), tables 2.2 and 2.4.
- **One disagreement between sources:** at look 2 of the five-look O'Brien-Fleming-type
  design NCSS prints 3.3569 and Stata prints 3.3570. The value computed here is 3.357012.
  The NCSS comparison therefore allows 1.5e-4 instead of 5e-5; this was decided when the
  disagreement was found and is stated in the test.

## Cross-checks against independent implementations

All are assertions in `tests/unit` and pass in the runs above.

- Two-proportion z test: z squared and p equal `scipy.stats.chi2_contingency` without
  continuity correction; z and p equal statsmodels `proportions_ztest` (relative 1e-10).
- Welch test: equals `scipy.stats.ttest_ind(equal_var=False)` and statsmodels
  `ttest_ind(usevar="unequal")` (relative 1e-10 for the statistic, 1e-9 for p).
- SRM p-value equals `scipy.stats.chisquare`.
- Bonferroni, Holm and Benjamini-Hochberg equal statsmodels `multipletests` (relative
  1e-12); Benjamini-Hochberg also equals `scipy.stats.false_discovery_control`.
- Sample size and power for means equal statsmodels `NormalIndPower` at allocation ratios
  1, 3 and 0.5.
- Sample size for proportions, 10% to 12%, alpha 0.05, power 0.8: 3,841 per arm, which is
  the value of the standard pooled-variance formula (3,840.85, rounded up).
  It is not compared with statsmodels, which uses an arcsine effect size for proportions.
- Delta-method ratio metric: the estimate equals the coefficient of an OLS on an arm
  indicator, and its standard error equals the cluster-robust (CR0) standard error from
  statsmodels after the factor sqrt((n - 1) / n) (relative 1e-9).
- Novelty trend: slope, standard error, t statistic, degrees of freedom and p equal
  statsmodels weighted least squares (relative 1e-10, 1e-9 for p).
- Cochran's Q, its p-value, I squared and the pooled effect equal statsmodels
  `combine_effects` (relative 1e-10).

## Monte Carlo validation suite

`abcopilot simulate --n-sims 5000 --seed 0`

| Check | Estimate | Expected | Tolerance | MC SE | Sims | Result |
|---|---|---|---|---|---|---|
| false_positive_rate[normal] | 0.0454 | 0.0500 | 0.0173 | 0.0031 | 5000 | PASS |
| false_positive_rate[binary] | 0.0524 | 0.0500 | 0.0223 | 0.0031 | 5000 | PASS |
| false_positive_rate[lognormal] | 0.0494 | 0.0500 | 0.0273 | 0.0031 | 5000 | PASS |
| false_positive_rate[normal], arms of 400 and 1,600 | 0.0516 | 0.0500 | 0.0173 | 0.0031 | 5000 | PASS |
| power[normal] | 0.7920 | 0.7982 | 0.0277 | 0.0057 | 5000 | PASS |
| power[binary], 10% to 12%, 3,841 per arm | 0.8000 | 0.8000 | 0.0326 | 0.0057 | 5000 | PASS |
| power[binary], arms of 2,000 and 6,000 | 0.6986 | 0.6870 | 0.0362 | 0.0066 | 5000 | PASS |
| ci_coverage[normal] | 0.9494 | 0.9500 | 0.0173 | 0.0031 | 5000 | PASS |
| ci_coverage[binary] | 0.9446 | 0.9500 | 0.0223 | 0.0031 | 5000 | PASS |
| ci_coverage[lognormal] | 0.9458 | 0.9500 | 0.0273 | 0.0031 | 5000 | PASS |
| peeking_fpr[looks=5,uncorrected] | 0.1430 | n/a | n/a | 0.0111 | 1000 | info |
| peeking_fpr[looks=5,bonferroni] | 0.0400 | 0.0500 | 0.0276 | 0.0069 | 1000 | PASS |
| fwer[m=10,uncorrected] | 0.3880 | 0.4013 | 0.0670 | 0.0155 | 1000 | PASS |
| fwer[m=10,holm] | 0.0410 | 0.0500 | 0.0276 | 0.0069 | 1000 | PASS |
| fwer[m=10,bonferroni] | 0.0540 | 0.0500 | 0.0276 | 0.0069 | 1000 | PASS |
| cuped_variance_ratio[rho=0.7] | 0.5110 | 0.5100 | 0.0865 | 0.0229 | 1000 | PASS |
| sequential_fpr[obrien-fleming,looks=5,normal] | 0.0442 | 0.0500 | 0.0173 | 0.0031 | 5000 | PASS |
| sequential_fpr[pocock,looks=5,normal] | 0.0468 | 0.0500 | 0.0173 | 0.0031 | 5000 | PASS |
| sequential_fpr[obrien-fleming,looks=4,binary] | 0.0552 | 0.0500 | 0.0223 | 0.0031 | 5000 | PASS |
| sequential_power[obrien-fleming,looks=5,normal] | 0.7854 | 0.7884 | 0.0281 | 0.0058 | 5000 | PASS |
| sequential_power[pocock,looks=5,normal] | 0.7192 | 0.7133 | 0.0306 | 0.0064 | 5000 | PASS |
| ratio_false_positive_rate[delta method] | 0.0482 | 0.0500 | 0.0223 | 0.0031 | 5000 | PASS |
| ratio_false_positive_rate[rows as units] | 0.1674 | n/a | n/a | 0.0053 | 5000 | info |
| ratio_ci_coverage[delta method] | 0.9494 | 0.9500 | 0.0223 | 0.0031 | 5000 | PASS |

22 checks pass and 2 are informational: they show what goes wrong without the correction
(five uncorrected looks, session rows treated as units) and have no pass criterion.

Tolerance = 4 x Monte Carlo standard error + a fixed slack for the approximation (0.005
normal, 0.01 binary, 0.015 lognormal). The rule is defined in `simulation.py` and was fixed
before the first run of each check; no tolerance was changed after a result was seen.
Limits of this evidence:

- The tolerances are wide. A miscalibration of about one percentage point would not be
  caught at 5,000 simulations.
- The sequential type I error with a binary metric (0.0552) is 0.0052 above 0.05, about
  1.7 Monte Carlo standard errors. That is compatible with 0.05 and also with a slight
  excess; this run cannot tell which.
- The sequential simulations use 1,000 units per arm (normal) and 4,000 per arm (binary,
  10% baseline) at the final look. Smaller experiments were not simulated.

## Monte Carlo checks of the new features

`python benchmarks/statistical_evidence.py` (second table). The same seeds and generators
are used by `tests/statistical/test_feature_monte_carlo.py`, which asserts the thresholds.

| Check | Observed | Threshold set before the run |
|---|---|---|
| Decision engine, 4 O'Brien-Fleming looks, no effect: share of 250 experiments with any Ship or Do not ship | 0.056 | at most 0.115 |
| Same design, true lift +5 pp: Ship / stopped before the last look / Do not ship, out of 100 | 87 / 71 / 0 | at least 80 / at least 40 / 0 |
| Novelty check, constant effect, 400 simulations: any significant trend | 0.0175 | at most 0.1036 |
| Novelty check, constant effect: decay warnings | 0.0100 | at most 0.0662 |
| Novelty check, lift halving every 3 days, 200 simulations: decay detected | 1.000 | at least 0.9 |
| Segments, no effect anywhere, 5 segments, Holm: any segment flagged, 400 simulations | 0.0500 | at most 0.1036 |
| Segments: all five simultaneous intervals cover zero | 0.9500 | at least 0.8964 |
| Segments, no effect anywhere, 5 segments, Bonferroni: any segment flagged | 0.0500 | at most 0.1036 |
| Segments, no effect anywhere, 5 segments, Benjamini-Hochberg: any segment flagged | 0.0500 | at most 0.1036 |
| Cochran's Q, equal effects in 5 segments, 400 simulations: rejections | 0.0400 | 0.05 within 0.0536 |
| Cochran's Q, one segment with +5 pp, 200 simulations: rejections | 0.945 | at least 0.9 |

With a few hundred simulations per row these thresholds only catch gross errors.

The older test `test_decision_engine_error_rates_on_ground_truth` (fixed-horizon engine,
200 null experiments and 100 with a true lift of +3 pp) also passes: it requires a wrong
call rate within binomial error of 5% on the nulls, at least 90 of 100 `Ship` on the true
effects and no `Do not ship`.

### Novelty check on whole datasets with a constant effect

`python benchmarks/statistical_evidence.py` (fourth table): 300 synthetic experiments of
20,000 users per row, seeds 1000 to 1299, analysed with the full pipeline.

| Data | Trend p < 0.05 | Decay warning | Growth | Reversal |
|---|---|---|---|---|
| Constant lift of +1.5 pp | 0.023 | 0.013 | 0.003 | 0.007 |
| No effect | 0.020 | 0.000 | 0.000 | 0.020 |
| No effect, 15% of non-converting control users lost (the sample ratio mismatch scenario) | 0.020 | 0.007 | 0.000 | 0.013 |

No threshold was fixed in advance for this table. It was run because the built-in sample
ratio mismatch scenario shows a novelty warning at its default seed (trend p = 0.0333)
although its generator has no time trend. Across 300 other seeds the check found a trend
in 2.0% of such datasets, below the 5% level of the trend test. The alarm at the default
seed is therefore a chance event, not a systematic artefact, and it is the reason the
check is worded as a warning and never as proof.

## A/A check

`python benchmarks/statistical_evidence.py` (third table), and the two commands of the
README on `examples/sample_sessions.csv` (2,000 users, 10,052 session rows, 1,000
re-labellings, seed 0).

| Data and analysis | False-positive rate at alpha 0.05 | Verdict |
|---|---|---|
| 6,000 independent users, binary metric, z test | 0.050 | calibrated |
| Session rows of 1,500 users, users re-labelled, Welch test on rows | 0.222 | inflated |
| Same sessions, delta-method ratio metric on user sums | 0.046 | calibrated |
| `sample_sessions.csv`, Welch test on rows (`abcopilot aa`, exit code 4) | 0.215 | inflated |
| `sample_sessions.csv`, delta-method ratio metric (`abcopilot aa`, exit code 0) | 0.051 | calibrated |

## Adversarial findings

Each row is asserted by tests in `tests/adversarial`. The numbers of the second row are
from `demo/output/report_sample_ratio_mismatch.md`, written by `python demo/run_demo.py`.

| Case | Behaviour |
|---|---|
| Sample ratio mismatch from losing 15% of the control non-converters while a real lift exists, naive p < 0.001 | Inconclusive, evidence "invalid" |
| The built-in sample ratio mismatch scenario at its default seed: no true effect, naive effect -0.019246 with p = 1.681e-05 (about 0.00002), treatment share 0.5326 (SRM p = 6.13e-19) | Inconclusive, evidence "invalid"; crossing a sequential boundary does not override it |
| Session rows analysed with the user declared as the unit | `unit_of_analysis` is blocking and the novelty check reports that it was not assessed |
| Session rows analysed with a row-level test and the unit declared for the A/A check | A/A check "inflated" (above 0.15), blocking |
| Session rows analysed without declaring any unit | Documented limitation: clustering cannot be detected, and a null dataset can produce a false verdict. With the unit declared the same data are refused; aggregated to users they are Inconclusive with valid evidence |
| Users present in both arms, also after aggregation | `contamination` blocking |
| One 5,000,000 revenue value in treatment | Outlier flagged, evidence "weak", not `Ship` |
| Missingness that differs between arms; a shifted pre-period covariate | Blocking |
| A sequential plan combined with unplanned looks; a look outside the plan; fractions that do not increase; more than 100 looks | Configuration error with a specific message |
| The final look declared on data that only reach an earlier look | Refused |
| A plan without a planned sample size | Accepted, with a note that the information fraction was not checked against the data |
| The final critical value reused at all five looks | The overall error exceeds 0.10 by numerical integration, which is why every look has its own critical value |
| A first look so early that its boundary is infinite | Inconclusive ("continue"), finite interval, no crash |
| Segments with fewer than 30 units per arm or without variation; units without a segment value | Skipped and listed with the reason; the correction family is the analysed segments only |
| A segment column with more than 30 levels, one level, or no level with 30 units per arm | Reported as not analysed; decision, evidence and reasons are identical to the analysis without segments |
| Segment labels of mixed types | Analysed with the labels read as text |
| A date or segment column that does not exist | Configuration error |
| No usable dates (missing, day-first format, free text, booleans) or fewer than 5 usable periods | Novelty check "not assessed"; decision, evidence and the primary estimate are identical to the analysis without it |
| Dates missing on part of the rows | Counted in the message; the primary estimate is unchanged |
| A stray date 180 years in the future | That period is excluded; the 14 real periods and the verdict of the check are unchanged |
| Markup in column names, labels and titles (HTML tags, Markdown links, pipes, backticks, line breaks) | Escaped in the Markdown report and in chart labels; JSON keeps the original text |
| Values of 1e300; zero, negative or text denominators; a ratio metric without a denominator | `ValueError` with a specific message |
| Spreadsheet formula text in a CSV used as dates and segments | Both checks "not assessed"; exit code 0 |
| Empty file, binary garbage, wrong columns, unterminated quote, non-CSV, over the row cap, missing file | CLI exit code 1 with `error:` |

## Defects found by the tests and fixed

- A segment column with mixed label types raised `TypeError`.
- Dates in the years 0001 and 9999 overflowed the day arithmetic of the novelty check.
- Values near 1e300 produced `NaN` statistics instead of an error.
- The planner accepted a binary baseline outside (0, 1) until sample-size time, and its
  guardrail error did not name the guardrail.
- The first version of the novelty check called a trend that crosses zero and continues on
  the other side a "decay"; it showed as a false warning on the built-in no-effect
  scenario. It is now classified as a reversal. The Monte Carlo thresholds of the check
  were not changed.
- In the dashboard, choosing another primary metric kept the metric type of the previous
  one.
- The CLI printed a traceback when its output pipe was closed early.
- Charts: overlapping labels, a missing zero on the effects axis and oversized histogram
  bars were found on screenshots and fixed.
- The built-in sample ratio mismatch scenario described its artefact as an apparent win.
  The data show an apparent loss (see the adversarial table). Found while checking the
  README against real output; the description was corrected and a test now derives the
  expected bias.

Tests whose expectation was wrong and was corrected (the code was right): three pre-existing
tests that pin the size of the validation suite were updated when it grew from 16 to 24
checks. Several tests written during this milestone had a wrong expectation when they
were first run and were corrected, for example a novelty example whose exact p-value is
0.0508 rather than below 0.05, a final look claimed with 37.5% of the planned sample
(which the engine refuses by design), and a guardrail example that used a seed with a
chance alarm. In no case was a statistical tolerance loosened.

## Performance

`python benchmarks/run_benchmarks.py --out benchmarks/results`: 3 runs per operation in
the clean virtual environment (Python 3.13.18, numpy 2.5.4, scipy 1.18.1, pandas 3.1.1,
2 CPUs shared with other jobs). Read the timings as orders of magnitude.

| Operation | Best | Median | Peak additional memory |
|---|---|---|---|
| analyze_experiment, 10,000 rows: CUPED + 1 guardrail | 11.2 ms | 12.1 ms | 2 MB |
| analyze_experiment, 100,000 rows: CUPED + 1 guardrail | 37.7 ms | 38.7 ms | 12 MB |
| analyze_experiment, 1,000,000 rows: CUPED + 1 guardrail | 333.9 ms | 335.6 ms | 116 MB |
| analyze_experiment, 100,000 rows: sequential look + novelty + segments | 124.9 ms | 127.2 ms | 17 MB |
| sequential_boundaries, 5 looks (O'Brien-Fleming type) | 4.2 ms | 4.5 ms | not measured |
| sequential_boundaries, 20 looks (O'Brien-Fleming type) | 39.0 ms | 39.8 ms | not measured |
| sequential_boundaries, 100 looks (O'Brien-Fleming type) | 685.9 ms | 688.6 ms | not measured |
| inflation_factor, 5 looks (Pocock type, power 0.8) | 25.2 ms | 26.6 ms | not measured |
| aa_check, 1,000 re-labellings of 20,000 units (binary) | 470.4 ms | 636.2 ms | not measured |
| aggregate_to_units, 999,801 session rows -> 200,000 users | 178.2 ms | 180.2 ms | 83 MB |
| analyze_experiment, ratio metric (delta method), 200,000 users | 62.4 ms | 64.3 ms | 24 MB |
| bootstrap_mean_diff, 2,000 resamples x 100,000 per arm | 1.80 s | 1.90 s | not measured |
| run_validation_suite, 5,000 simulations (24 checks) | 14.04 s | 14.14 s | not measured |

No comparison with other libraries was run.

## Security

| Tool | Scope | Result |
|---|---|---|
| ruff rule set `S` (part of `ruff check .`) | whole repository | No finding in shipped code. In `tests/`, `S101` (assertions) and `S603` (the tests start this repository's own scripts with fixed arguments and no shell) are switched off |
| `bandit -r src app examples skills demo benchmarks` (bandit 1.9.4) | 5,200 lines of code | No issues identified; 0 lines skipped with `# nosec` |
| `pip-audit --skip-editable` (pip-audit 2.10.1) in a clean virtual environment | every installed dependency | No known vulnerabilities found |
| Keyword search of the tracked files for credentials and email addresses | all tracked files except the vendored Plotly bundle | No credential; one address, the GitHub no-reply commit identity in `PROJECT_STATE.md` |

bandit and pip-audit gave the same results in the `audit` job of CI run 43579387120.
Nothing had to be fixed or suppressed. Details and the design measures are in
[SECURITY.md](SECURITY.md).

## Not verified, not done

- **No independent review.** Nobody other than the author of the code, human or agent, has
  reviewed the statistics or the implementation. The six-role review planned for this
  project has not been run.
- **The dashboard has not been operated by a person.** It is tested through `AppTest`, a
  headless server start and seven screenshots of the light theme. The dark theme was not
  inspected in the dashboard, and there was no accessibility audit.
- **The Agent Skill has not been loaded in Claude Code.** Its frontmatter, the link in
  `.claude/skills/` and the script are tested; its behaviour as a skill is not.
- **No dedicated secret scanner** (gitleaks or similar) was run, only the keyword search.
- **`demo/capture_screenshots.cjs`** is a helper that was run by hand and is not tested.
- **Published values:** two constants were quoted from memory and one group was checked
  against a secondary source only (see above).
- **Statistical limits:** no futility boundary, no bias-adjusted estimate after an early
  stop, no anytime-valid inference, no CUPED or sample-size formula for ratio metrics, one
  treatment against one control, missing values dropped under a missing-completely-at-random
  assumption. Small-sample behaviour of the sequential rule was not simulated.
- **Not on `main`.** All of this is on pull request #1; `main` holds the auto-generated
  README.

## Release recommendation

**Do not publish yet.** The package is tested in five layers, checked against published
values and independent implementations, and green in CI on three Python versions with the
security audit. The open gates are the ones listed above: an independent review, a person
operating the dashboard, the skill loaded in Claude Code, a secret scan, the merge and the
owner's decision about the initial commit.
