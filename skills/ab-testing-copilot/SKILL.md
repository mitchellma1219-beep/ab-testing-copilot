---
name: ab-testing-copilot
description: Design, diagnose, analyze and interpret A/B experiments with statistically defensible output. Use when the user asks for a sample size, power or MDE calculation, experiment duration, an SRM check, analysis of experiment results (conversion or continuous metrics, CUPED, guardrails), a ship / no-ship recommendation, or wants to validate A/B testing statistics by simulation.
license: MIT
compatibility: Requires Python 3.11+ with numpy, scipy, pandas and pydantic.
---

# A/B Testing Copilot

All numbers must come from the bundled script. Never compute statistics by hand or from
memory, and never state significance, lift or impact that the script did not return.

## Run

`python scripts/abcopilot.py <command> ...` (paths relative to this skill directory).
The script uses the installed `ab_testing_copilot` package, or the repository `src/` if
the skill is used from a checkout.

| Task | Command |
|---|---|
| Sample size / duration | `design --baseline 0.10 --mde 0.01 [--relative] [--power 0.8] [--alpha 0.05] [--ratio 1] [--daily-units N --traffic-share S]` |
| Continuous metric design | `design --metric-type continuous --std-dev 25 --mde 1.5 [--baseline 40]` |
| SRM check from counts | `srm N_CONTROL N_TREATMENT [--expected-share 0.5]` |
| Full analysis of a CSV | `analyze data.csv --metric COL --metric-type binary\|continuous [--guardrail COL:TYPE:higher\|lower:MARGIN]... [--unit-col ID] [--covariate PRE_COL] [--looks K] [--mde X] [--format json]` |
| Validate the statistics | `simulate [--n-sims 5000] [--seed 0]` |

Exit codes: 0 ok, 1 invalid input, 2 SRM detected, 3 a simulation check failed.

## Workflow

1. **Before designing**, get from the user: primary metric and direction, baseline (and
   std dev for continuous metrics), MDE, traffic per day. Ask rather than guess; state any
   assumption you must make.
2. **Before analysing**, confirm the unit of randomisation and pass `--unit-col`; pass
   `--looks` if results were checked before the planned end; pass a `--covariate` only if
   it was measured before assignment.
3. Run the command and report the decision, effect, interval, evidence quality and every
   diagnostic that did not pass, in plain language.
4. If the decision is `Inconclusive` with evidence quality `invalid`, do not discuss the
   effect size as if it were real. Explain what broke and what to investigate.

## Rules

- A non-significant result is "inconclusive", not "no effect".
- Segment cuts are exploratory. Label them as hypotheses for a follow-up test.
- Do not change alpha, the test or the outlier treatment after seeing results.
- Do not translate lift into revenue unless the user supplies the conversion values.

Methods, formulas and known limitations: `references/methodology.md`.
