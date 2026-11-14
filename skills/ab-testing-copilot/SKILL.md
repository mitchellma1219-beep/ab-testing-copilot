---
name: ab-testing-copilot
description: Design, diagnose, analyze and interpret A/B experiments with statistically defensible output. Use when the user asks for an experiment plan or pre-registration, a sample size, power or MDE calculation, experiment duration, interim looks or group-sequential boundaries, an SRM or A/A check, analysis of experiment results (conversion, continuous or ratio metrics, CUPED, guardrails, novelty effect, segment effects), a ship / no-ship recommendation, or wants to validate A/B testing statistics by simulation.
license: MIT
compatibility: Requires Python 3.11+ with numpy, scipy, pandas and pydantic.
---

# A/B Testing Copilot

All numbers must come from the bundled script. Never compute statistics by hand or from
memory, and never state significance, lift or impact that the script did not return.

## Run

`python scripts/abcopilot.py <command> ...` (paths relative to this skill directory).
The script uses the installed `ab_testing_copilot` package, or the repository `src/` if
the skill is used from a checkout. `<command> --help` lists every option.

| Task | Command |
|---|---|
| Experiment plan to pre-register | `plan --hypothesis TEXT --metric COL --metric-type binary\|continuous --direction higher\|lower --baseline B [--std-dev S] --mde M --mde-scale absolute\|relative --alpha A --power P --treatment-share S --unit ID --daily-units N --traffic-share S (--guardrail NAME:TYPE:higher\|lower:MARGIN ... \| --no-guardrails REASON) --looks K [--sequential obrien-fleming\|pocock]` |
| Sample size / duration | `design --baseline 0.10 --mde 0.01 [--relative] [--power 0.8] [--alpha 0.05] [--ratio 1] [--daily-units N --traffic-share S] [--sequential METHOD --looks K]`; continuous: `--metric-type continuous --std-dev 25 --mde 1.5` |
| Sequential boundaries | `sequential --method obrien-fleming\|pocock (--looks K \| --info-fractions 0.3,0.6,1) [--alpha 0.05] [--power 0.8]` |
| SRM check from counts | `srm N_CONTROL N_TREATMENT [--expected-share 0.5]` |
| Full analysis of a CSV | `analyze data.csv --metric COL --metric-type binary\|continuous\|ratio [--denominator COL] [--guardrail COL:TYPE:higher\|lower:MARGIN]... [--unit-col ID] [--aggregate COL=sum,COL=unique] [--covariate PRE_COL] [--mde X] [--date-col DATE] [--segment-col SEG] [--aa-relabels 1000] [--format json]` |
| ... looked at more than once | add `--looks K` (unplanned peeks, Bonferroni) or `--sequential METHOD --planned-looks K --look k [--planned-n N]` (pre-registered design) |
| A/A check on the user's data | `aa data.csv --metric COL --metric-type TYPE [--denominator COL] [--unit-col ID]` |
| Validate the statistics | `simulate [--n-sims 5000] [--seed 0]` |

Exit codes: 0 ok, 1 invalid input, 2 SRM detected, 3 a simulation check failed, 4 the A/A
check found an inflated false-positive rate.

## Workflow

1. **Planning.** `plan` refuses to run until every input is stated and lists what is
   missing. Ask the user for each item. Never invent a baseline, MDE, alpha, power,
   traffic figure or guardrail margin; state any assumption you must make.
2. **Before analysing**, confirm the unit of randomisation and pass `--unit-col`. If rows
   are finer than that unit (sessions per user), use `--aggregate` or a ratio metric.
   Pass a `--covariate` only if it was measured before assignment.
3. **Looks.** Use `--sequential` only for looks that were planned before the experiment
   started; any other early look is `--looks`. At an interim look, `Inconclusive` means
   "continue to the next planned look", not "no effect".
4. Run the command and report the decision, effect, interval, evidence quality and every
   diagnostic that did not pass, in plain language.
5. If the decision is `Inconclusive` with evidence quality `invalid`, do not discuss the
   effect size as if it were real. Explain what broke and what to investigate.

## Rules

- A non-significant result is "inconclusive", not "no effect".
- Segment results are exploratory: report them as hypotheses for a follow-up test and
  never use them to change the recommendation.
- The novelty check is a warning with its evidence, not proof of a novelty effect.
- Do not change alpha, the test, the looks or the outlier treatment after seeing results.
- Do not translate lift into revenue unless the user supplies the conversion values.

Methods, formulas, assumptions and known limitations: `references/methodology.md`.
