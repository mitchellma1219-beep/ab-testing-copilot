# A/B Testing Copilot: portfolio summary

A statistics-first toolkit that plans, validates, analyses and decides randomised
experiments, delivered as a Python package, a command-line tool, a Streamlit dashboard and
an Agent Skill. Its rule is to prefer "Inconclusive" over a confident wrong answer.

This document is written for reviewers and for interview preparation (Data Analyst,
Business Analyst, Product Analyst, AI Consultant and Forward-Deployed Engineer roles).
Every measured number in it appears in [QUALITY_REPORT.md](QUALITY_REPORT.md), together
with the command that produced it.

## How this was built

The owner of this repository specified the product, directed the work and verified the
results. The code, the tests and the documentation were written by an AI coding agent
(Claude Code) under that direction. The commit history shows it: every commit after the
initial one carries a `Co-Authored-By: Claude` trailer and a session link.

What that means for anyone presenting this project:

- **Fair to claim:** defining the problem and the scope; setting the statistical rules
  (prefer Inconclusive, never change a method to force a conclusion, tolerances fixed
  before a simulation runs, cross-checks against published values); setting the quality
  gates (tests, coverage, types, security scans, CI on three Python versions); reading the
  evidence and deciding what is and is not ready.
- **Not fair to claim:** hand-written implementation, users, adoption, production use, or
  any result that is not in the quality report. The project is unreleased and has not been
  reviewed by a second person.

## 1. Problem

A/B tests decide what ships. The arithmetic of a test is easy; the ways to get a confident
wrong answer are many, and most calculators do not check for them:

- looking at the results every day and stopping at the first p < 0.05;
- a broken sample ratio, which means the analysed units are not the randomised ones;
- analysing sessions or page views when users were randomised;
- reading "not significant" as "no effect", or a non-significant guardrail as "safe";
- an early novelty spike reported as the lasting effect;
- a segment found after the fact and presented as a finding.

The project encodes the checks an experienced experimenter would run, in a tool that says
what it assumed, refuses to fill gaps with guesses and returns one of three verdicts with
its reasons: Ship, Do not ship, Inconclusive.

## 2. Business relevance

- **A wrong launch decision has a cost in both directions.** Shipping a change that does
  not work spends engineering and carries risk for nothing; discarding one that works
  forgoes its benefit. A tool that separates "we do not know yet" from "it does not work"
  changes what the team does next: collect more data, fix the instrumentation, or stop.
- **Validity comes before the estimate.** In the built-in sample ratio mismatch scenario a
  treatment that does nothing looks significantly worse because a logging bug loses control
  users. The useful output there is not an effect size but an instruction: find the bug.
- **Speed without self-deception.** Teams want to stop early. A pre-registered sequential
  design allows it at a known error rate, instead of informal peeking.
- **A shared, auditable record.** The plan (hypothesis, metrics, margins, sample size,
  looks, decision rule) is written before the data arrive, and the report states the
  method, the assumptions and every check, as Markdown and JSON.

What each target role can point to:

| Role | What the project shows |
|---|---|
| Data Analyst | Hypothesis tests, intervals, power, multiple comparisons, and the diagnostics that decide whether a number can be trusted |
| Business Analyst | A decision rule that turns statistics into Ship / Do not ship / Inconclusive with reasons a stakeholder can read |
| Product Analyst | Experiment planning, guardrails with margins, sample ratio mismatch, novelty effects, ratio metrics such as click-through rate |
| AI Consultant | Directing an AI coding agent with explicit acceptance criteria, and checking its output against evidence instead of trusting it |
| Forward-Deployed Engineer | A tested package with a CLI, a dashboard and an agent skill; CI on three Python versions; security scans; honest documentation of limits |

## 3. Architecture

One package holds all statistics; four thin entry points (CLI, Python API, Streamlit
dashboard, Agent Skill script) collect inputs and present what the package returns.

1. `experiment.py` validates a table against an `ExperimentConfig` and runs the pipeline.
2. `diagnostics.py`, `aa.py` and `novelty.py` check validity; `sequential.py` supplies the
   critical value of the current look; `analysis.py` estimates effects.
3. `decision.py` combines the primary estimate, the guardrail verdicts and the diagnostics.
   A blocking diagnostic overrides any effect size.
4. `heterogeneity.py` is attached to the report after the decision and is never an input
   to it, so "exploratory results do not decide" is a property of the data flow.
5. Every result is a frozen pydantic model that renders to Markdown, serialises to strict
   JSON and feeds the pure chart builders in `charts.py`.

`simulation.py` calls the same vectorised cores as the reports, so the Monte Carlo suite
validates the code that users run. Module table, data-flow diagram and trade-offs:
[ARCHITECTURE.md](ARCHITECTURE.md).

## 4. Key algorithms

| Algorithm | Purpose | How it is checked |
|---|---|---|
| Lan-DeMets alpha spending (O'Brien-Fleming type, Pocock type); boundaries by recursive numerical integration with Gauss-Legendre quadrature and root finding | Critical value for each planned look; power and sample-size inflation of the design | Published Stata and gsDesign values; scipy multivariate normal integration; simulation |
| Delta method for ratio metrics on unit-level sums | Click-through rate and similar metrics when rows are finer than the randomised unit | Equal to the cluster-robust sandwich variance from statsmodels; simulation |
| Two-proportion z test, Welch t test, delta-method relative lift | Effects and intervals for binary and continuous metrics | scipy, statsmodels |
| CUPED | Variance reduction with a pre-experiment covariate | Simulation of the variance ratio |
| Chi-square sample ratio test; A/A check by random re-labelling with an exact binomial verdict | Is the randomisation intact; is the analysis calibrated on this data | scipy; simulation on independent and clustered data |
| Weighted least-squares trend of per-period effects | Novelty-effect warning | statsmodels WLS; simulation of false alarms and detection |
| Holm, Bonferroni and Benjamini-Hochberg adjustments; simultaneous intervals; Cochran's Q | Exploratory segment analysis | statsmodels; simulation of the family-wise error |
| Guardrails as non-inferiority tests with a stated margin | "Not significant" is not accepted as "safe" | Unit and adversarial tests |

## 5. Technical trade-offs

| Decision | Alternative | Reason |
|---|---|---|
| Write the boundary computation in the package | Depend on an R package or a clinical-trials library | numpy, scipy and statsmodels do not provide it, and a small quadrature engine can be checked against published values |
| Apply each look's critical value to the ordinary test (nominal-level approach) | Dedicated sequential p-values and bias-adjusted estimates | One estimation path for every metric type; the cost, conservative intervals and an overstated estimate after an early stop, is stated in every sequential report |
| Bonferroni for looks that were not planned | Use a spending boundary after the fact | A boundary is only valid if it was fixed in advance |
| Refuse repeated rows per unit | Fit a mixed model | Aggregation and the delta method cover the common cases with one formula each |
| Novelty check as a conservative linear trend | Fit an exponential decay model | It is a warning, so robustness matters more than fit |
| Segments attached after the decision | Let heterogeneity change the verdict | Exploratory analysis cannot leak into a confirmatory decision |
| Streamlit script as a thin layer over the package | Logic in UI callbacks | Everything on screen can be reproduced from the CLI, and the UI can be tested by driving the real script |
| Synthetic data only | Real datasets | A known ground truth makes every test checkable, and no personal data enters the repository |

## 6. Statistical methodology

Each method was admitted on four kinds of evidence:

1. **A reference.** The method and its assumptions are documented in the
   [methodology reference](skills/ab-testing-copilot/references/methodology.md).
2. **A published value or an independent implementation.** Stata, NCSS and gsDesign
   documentation for the boundaries; scipy and statsmodels for the tests, the adjustments,
   the sandwich variance, weighted least squares and Cochran's Q.
3. **A seeded simulation with a tolerance fixed before the first run** (four Monte Carlo
   standard errors plus a stated slack). No tolerance was loosened after a result was seen.
4. **Adversarial tests** for misuse: wrong unit of analysis, contaminated samples, a
   sequential boundary applied to the wrong look, tiny segments, unusable dates, hostile
   input.

Rules that the code enforces:

- A blocking validity problem makes the result Inconclusive whatever the effect size.
- At an interim look, "not crossed" means "continue", never "no effect".
- Segment results are labelled exploratory and cannot change the decision.
- The novelty check is a warning with its evidence, never proof.
- The planner lists missing inputs instead of guessing them.
- A check that cannot run says "not assessed" instead of passing silently.

## 7. Reliability and security considerations

- **Input.** CSV only, with row caps; structural problems raise a specific error; no
  `eval`, pickle, shell call or network access touches user data.
- **Resource bounds.** Caps on simulations, re-labellings, looks, periods and segment
  levels.
- **Output.** Text that comes from the data is escaped in Markdown reports and in chart
  labels; JSON is strict.
- **Determinism.** Seeded simulations and synthetic data; a second run of the demo writes
  the same files.
- **Automation.** GitHub Actions runs lint, strict type checking and the whole suite with
  a coverage gate on Python 3.11, 3.12 and 3.13, and a separate audit job runs bandit and
  pip-audit.
- **Honest limits.** The quality report lists what was not verified. Details:
  [SECURITY.md](SECURITY.md).

## 8. Demonstrated capabilities

- Framing an analytical product: which decisions it supports, which errors matter and
  what it must refuse to do.
- Experimental statistics at working depth: power and sample size, sequential testing,
  variance reduction, ratio metrics, multiplicity, validity diagnostics.
- Specifying work for an AI coding agent as testable acceptance criteria, and holding the
  result to evidence: published values, independent implementations, simulation.
- Statistical quality assurance: tolerances fixed in advance, adversarial cases, a written
  record of defects found and of what remains unverified.
- Communicating uncertainty to non-specialists: three verdicts, an evidence rating,
  reasons in plain language, charts with table views.
- Engineering hygiene: typed code, layered tests, CI, security scanning, reproducible
  demo and benchmarks.

## 9. Verified outcomes

All figures are from [QUALITY_REPORT.md](QUALITY_REPORT.md), measured on 2026-11-14.

**Tests and automation**

- 447 tests in five layers (279 unit, 31 integration, 66 adversarial, 41 statistical,
  30 UI) pass on Python 3.11, 3.12 and 3.13 in CI run 43579387120.
- Line coverage of the package is 99.96% (2,520 statements, 1 missed); the CI gate is 85%.
- `ruff` and strict `mypy` are clean. bandit reports no issues over 5,200 lines of code;
  pip-audit reports no known vulnerabilities.

**Sequential testing**

- Five O'Brien-Fleming-type looks: computed critical values 4.876885, 3.357012, 2.680280,
  2.289817, 2.031032 against the Stata manual's 4.8769, 3.3570, 2.6803, 2.2898, 2.0310.
- Four Pocock-type looks match the gsDesign manual to six decimals (2.368328, 2.367524,
  2.358168, 2.350030).
- Sample-size inflation factor 1.024718 against Stata's 1.0247.
- Simulated overall false-positive rate (5,000 simulations): 0.0442 and 0.0468 for five
  O'Brien-Fleming-type and Pocock-type looks, 0.0552 for four looks on a binary metric,
  against a target of 0.05. Five uncorrected looks give 0.1430.
- The decision engine run across four looks: 0.056 of 250 null experiments ended in any
  Ship or Do not ship (threshold 0.115); with a true lift of +5 points, 87 of 100 shipped,
  71 of them before the last look, and none ended in Do not ship.

**Unit of analysis**

- Session rows treated as units: false-positive rate 0.1674. Delta method on user sums:
  0.0482, with interval coverage 0.9494.
- A/A check on the bundled sessions file: 0.215 for a row-level test, 0.051 for the
  delta-method ratio metric.

**Other checks**

- Novelty check: 0.0175 false trend rate on a constant effect; 1.000 detection when the
  lift halves every three days.
- Segments: family-wise error 0.0500 with Holm correction; all simultaneous intervals
  cover zero in 0.9500 of null simulations.
- CUPED: variance ratio 0.5110 against 0.5100 expected at a correlation of 0.7.
- Performance: 1,000,000 rows analysed in 333.9 ms (best of three); boundaries for five
  looks in 4.2 ms.

**What the same report says is not verified:** no independent review; the dashboard has
not been operated by a person; the skill has not been loaded in Claude Code; no dedicated
secret scanner; two reference constants were quoted from memory. The Monte Carlo
tolerances are wide enough to miss a miscalibration of about one percentage point.

## 10. Future improvements

- Futility boundaries and bias-adjusted estimates after an early stop.
- Anytime-valid inference (always-valid confidence sequences) for continuous monitoring.
- CUPED and sample-size formulas for ratio metrics.
- More than one treatment arm, with the multiplicity handled in the decision rule.
- Stratified and cluster-randomised designs analysed by regression.
- An independent statistical review, and a person operating the dashboard.
- A secret scanner in CI; a release to a package index after the open gates are closed.

## 11. Resume bullet candidates

Each bullet states the owner's role as it was (specified, directed, verified) and uses
only measured figures.

1. Specified, directed and verified an open-source A/B testing toolkit (Python package,
   CLI, Streamlit dashboard) built with an AI coding agent; it covers power analysis,
   sample ratio mismatch detection, CUPED, ratio metrics and group-sequential testing and
   returns Ship / Do not ship / Inconclusive decisions with stated reasons.
2. Defined statistical acceptance criteria and verified them against evidence: sequential
   boundaries reproduce published Stata and gsDesign values to four and six decimals, and
   Monte Carlo simulation (5,000 runs) holds the false-positive rate of five-look designs
   at 4.4% and 4.7% against a 5% target, where five uncorrected looks give 14.3%.
3. Set quality gates enforced by GitHub Actions on Python 3.11 to 3.13: 447 automated
   tests (unit, integration, adversarial, statistical, UI), 99.96% line coverage, strict
   type checking, and bandit and pip-audit security scans with no findings.

Tailoring: lead with bullet 1 for analyst roles, with bullet 2 where experimentation is
the core of the job, and with bullet 3 for AI consulting and forward-deployed roles, where
directing an agent and holding it to gates is the skill on show. Do not replace
"specified, directed and verified" with "built" or "developed" without the phrase "with an
AI coding agent".

## 12. Elevator pitch (60 seconds)

"Most A/B testing tools give you a p-value. The expensive mistakes happen around it: people
peek and stop early, the traffic split is quietly broken, or sessions get analysed when
users were randomised. I specified and directed the build of a toolkit that checks for
those things first and is willing to say 'Inconclusive'. It plans an experiment without
guessing missing inputs, supports pre-registered early stopping with alpha-spending
boundaries, flags sample ratio mismatch and novelty effects, and returns Ship, Do not
ship or Inconclusive with its reasons. I built it with an AI coding agent, and my part was
the specification and the verification: the boundaries reproduce published values, the
error rates are confirmed by simulation, and 447 tests run in CI on three Python versions.
The quality report also lists what is not verified yet, which I think matters as much as
the list of what is."

## 13. Technical walkthrough (2 minutes)

"The core is a Python package, and everything else is a thin layer over it: a CLI, a
Streamlit dashboard and an agent skill.

An analysis starts from a table and a configuration that names the metrics, the
guardrails with their margins, the randomisation unit and the planned looks. The pipeline
checks validity first: sample ratio mismatch with a chi-square test, units that appear in
both arms, repeated rows per unit, differential missing data, outliers, covariate balance.
Any blocking problem makes the result Inconclusive, whatever the effect size.

Then it picks the significance level for this look. For a pre-registered sequential design
it computes Lan-DeMets alpha-spending boundaries by numerical integration. For five
O'Brien-Fleming-type looks the critical values run from 4.88 at the first look to 2.03 at
the last, and they match the Stata manual to four decimals. Looks that were not planned
get a Bonferroni penalty, because a boundary chosen after the fact is not valid.

Effects come from a two-proportion z test, a Welch test or, for ratio metrics like
click-through rate, the delta method on user-level sums. That matters: in simulation,
treating session rows as independent gives a false-positive rate of about 17% instead of
5%, and the delta method gives 4.8%.

The decision rule is deliberately simple. Ship needs an interval entirely on the good
side and every guardrail cleared against its margin. A guardrail that is merely not
significant does not count as safe. Segment analysis is attached after the decision and
labelled exploratory, so it cannot change the verdict.

For verification there are four kinds of evidence: published values, independent
implementations in scipy and statsmodels, seeded Monte Carlo with tolerances fixed in
advance, and adversarial tests for misuse. I directed an AI coding agent to build it and
held it to those gates. What I would do next is get an independent statistical review,
because nobody else has checked it yet."

## 14. Interview questions with model answers

**1. Why is it wrong to check a test every day and stop when p < 0.05? What does the tool
do instead?**

Every look is another chance for noise to cross the threshold. The statistics at
successive looks are correlated but not identical, so the chance that at least one of them
exceeds 1.96 grows with the number of looks. For five equally spaced looks the overall
false-positive rate is about 14%, not 5%: the engine computes 0.1417 by numerical
integration and a simulation gives 0.1430. The remedy is to fix the number of looks in
advance and spend the 5% across them with an alpha-spending function, so each look has its
own critical value. Simulated, that design rejects 0.0442 of null experiments. If the looks
were not planned, no boundary can be justified afterwards, so the tool divides alpha by
the number of looks (Bonferroni), which is valid without assumptions about timing but
conservative: 0.0400 in the peeking simulation.

**2. O'Brien-Fleming type or Pocock type: how do you choose?**

Both spend the same total alpha; they differ in when. A Pocock-type boundary is nearly
flat, about 2.37 to 2.35 for four looks, so stopping early is easy, but the final look
also needs 2.35 instead of 1.96 and the design loses power for a given maximum sample: in
the simulation with five looks, 0.7192 against 0.7854 for the O'Brien-Fleming type. The
O'Brien-Fleming type is very strict early (4.33 at the first of four looks) and close to a
fixed-horizon test at the end (2.01), at the price of a maximum sample about 2.5% larger
(inflation factor 1.0247 for five looks). I would default to the O'Brien-Fleming type in
product work: early estimates are noisy and overstated, and the final answer is what
matters. The Pocock type fits cases where stopping early has value in itself, for example
when exposure is costly, and a larger maximum sample is affordable. Either way the choice
is made before the experiment starts.

**3. How are the boundaries computed, and how do you know the numbers are right?**

Under the null hypothesis the test statistics at the looks are jointly normal with
independent increments. The probability of crossing at look k without having stopped
before is a k-dimensional integral, which can be computed recursively: carry forward the
density of the statistic among experiments that have not stopped, add the next normal
increment, and integrate the part beyond the boundary. The engine does this with
Gauss-Legendre quadrature and solves for each critical value so that the cumulative
crossing probability equals the alpha spent so far. The evidence is layered. The values
match the Stata manual to four decimals and the gsDesign manual to six. An independent
method, scipy's multivariate normal integration, gives an overall alpha of 0.05000000 and
0.05000002. A grid three times finer changes nothing to nine decimals. Simulation confirms
the error rate on generated data. The limit: two reference constants were quoted from
memory, and nobody else has reviewed the implementation; the quality report says so.

**4. The naive test shows p = 0.00002 and the tool says Inconclusive. Why?**

Because the sample ratio is broken. The design was 50/50, but 53.26% of the analysed units
are in treatment, and the chi-square test for that split gives p = 6.13e-19. A sample
ratio mismatch means the units that were analysed are not the units that were randomised,
so the comparison is no longer protected by randomisation. In this built-in scenario a
logging bug loses 15% of the control users who did not convert. That inflates the control
conversion rate, and a treatment that does nothing looks 1.9 points worse. No statistical
correction repairs this, because the missing units are missing for a reason related to the
outcome. The engine therefore returns Inconclusive with evidence quality "invalid", even if
a sequential boundary was crossed, and the next step is engineering: find where units are
lost, fix it, and run the experiment again.

**5. Users are randomised, but the table has one row per session. What goes wrong with a
t test on sessions?**

Sessions of one user are correlated, so the data hold fewer independent observations than
rows. The standard error comes out too small and false positives multiply: 0.1674 instead
of 0.05 in the simulation, and 21.5% in the A/A check on the bundled sessions file. There
are two sound options. Aggregate to one row per user. Or, for a ratio such as clicks per
impression, where numerator and denominator both vary by user, use the delta method on
user-level sums; it linearises the ratio and takes the variance across users. That is
equivalent to a cluster-robust variance, which the tests confirm against statsmodels, and
it gives 0.0482 in simulation and 5.1% in the A/A check. The tool refuses repeated rows
per declared unit instead of analysing them. Its limit is that it cannot detect clustering
when the unit column is not declared.

**6. A guardrail metric shows no significant change. Has the guardrail passed?**

Not on that basis. "Not significant" can simply mean the test had little power for that
metric; absence of evidence of harm is not evidence of its absence. The tool treats a
guardrail as a non-inferiority question. The team states the relative harm it tolerates,
say 2%, and the guardrail passes only if the confidence interval rules out harm beyond
that margin. If the whole interval lies on the harmful side, it is a regression and the
verdict is Do not ship, even when the primary metric improved. If the interval reaches
past the margin without excluding zero, the guardrail is uncertain, and a positive primary
result becomes Inconclusive instead of Ship. With unplanned looks the tool is asymmetric on
purpose: a regression is still flagged at the unadjusted level, while "safe" has to hold
at the stricter Bonferroni level.

**7. The primary result is not significant. Does the tool conclude that there is no
effect?**

No. It returns Inconclusive and says which kind. If a minimum detectable effect was
declared and the interval excludes improvements that large, the report says that more data
is unlikely to reveal a worthwhile win, which is a useful reason to stop. If the interval
still contains the minimum detectable effect, the test was underpowered for the effect of
interest and the honest statement is that the question is open. At an interim look of a
sequential design the message is "continue to the next planned look"; the design has no
futility rule, so an early look can never be read as evidence of no effect. This
distinction is the point of the product: a p-value above 0.05 is not a finding.

**8. The overall effect is small, but one segment shows a large, significant lift. Do we
ship to that segment?**

Not from this experiment. Segments are a search: with five segments and no real effect
anywhere, an unadjusted look finds something "significant" far more often than 5% of the
time. The tool adjusts the p-values (Holm by default; the simulated family-wise error is
0.0500), reports simultaneous intervals, and tests whether the effects differ at all with
Cochran's Q. Even after adjustment the result is labelled exploratory, because the segment
was not the pre-registered hypothesis and the choice of cut was made with the data in
view. The data flow enforces this: segment analysis is attached to the report after the
decision is made. The right next step is a new experiment with the segment as its
pre-registered population.

**9. How does the novelty check work, and what are its limits?**

It estimates the treatment effect per period, fits a weighted linear trend through those
estimates, and inflates the standard error when the points scatter more than their own
standard errors predict. A significant trend towards zero is reported as a possible
novelty effect, with the slope, the fitted start and end effects and the first-half and
second-half estimates as evidence. It is conservative: on a constant effect it raised a
trend in 0.0175 of simulations, and it detected a lift that halves every three days in
1.000 of them. The limits are real. A changing mix of users over time, seasonality or
chance produce the same pattern; one of the built-in scenarios shows such a chance alarm
at its default seed. A linear trend is a crude model of decay, and effects that grow as
users learn a feature need the same care. So the output is a warning that weakens the
evidence rating, never a verdict; the remedy is to run longer or compare cohorts by
exposure date.

**10. You built this with an AI coding agent. What was your part, and how do you know the
result is right?**

My part was the specification, the direction and the verification. I decided what the
product must do and must refuse to do, and I set acceptance criteria that do not depend on
trusting the agent: boundaries must reproduce published values, error rates must hold in
simulation with tolerances fixed in advance, every method needs an independent cross-check,
and tests may not be weakened to pass. The process surfaced real defects, which is the
reason to trust it more than a clean first run: the novelty check first mislabelled a
trend that crosses zero, mixed segment labels crashed, and a demo scenario described its
own artefact with the wrong sign. I do not claim the result is fully correct. Nobody else
has reviewed the statistics, the dashboard has not been operated by a person, and the
simulation tolerances would miss a miscalibration of about one percentage point. Those
items are written down in the quality report, and they are what I would close first.

## 15. Suggestions for a LinkedIn showcase post

Publish only after the repository is public and the open gates in the quality report are
closed, or say plainly that it is work in progress.

- **Open with the problem, not the tool.** For example: "A p-value of 0.00002 and the
  right answer was still 'we do not know'." Then explain the sample ratio mismatch
  scenario in two sentences.
- **Show one picture.** `demo/screenshots/06_decision_report.png` (a mismatch overriding
  a "significant" result) or `demo/screenshots/04_statistical_results.png`.
- **Give one or two measured facts, with their source.** Five uncorrected looks: 14.3%
  false positives in simulation; the pre-registered design: 4.4%. Session rows as units:
  16.7%; the delta method: 4.8%. Link to the quality report.
- **Say how it was built.** One sentence: specified, directed and verified by you, written
  with an AI coding agent. It is the more interesting story, and the commit history shows
  it anyway.
- **Say what is not done.** Naming the open items (independent review, futility
  boundaries) reads as judgement, not weakness.
- **End with a question** that invites experience, such as how other teams handle peeking.
- **Avoid:** adoption or usage claims, "production-ready", "built from scratch", and any
  number that is not in the quality report.

Draft to adapt:

> A p-value of 0.00002, and the right answer was still "we do not know".
>
> In one of the test scenarios of my A/B testing project, a logging bug drops 15% of the
> control users who did not convert. The treatment does nothing, yet it looks clearly
> worse. The only useful output is "the sample ratio is broken, find the bug".
>
> That is the idea behind A/B Testing Copilot: check validity first, and be willing to say
> Inconclusive. It plans experiments without guessing missing inputs, supports
> pre-registered early stopping, handles ratio metrics, and explains every verdict.
>
> I specified, directed and verified it; the code was written with an AI coding agent.
> Verification was my part: published boundary values reproduced, error rates confirmed by
> simulation (five unplanned looks: 14.3% false positives; the planned design: 4.4%),
> 447 tests in CI. The quality report also lists what is not verified yet.
>
> How does your team handle peeking?
