# Experiment plan

Every number below follows from the inputs that were supplied. Nothing was assumed on your behalf.

## Hypothesis

A shorter checkout form raises purchase conversion because fewer users abandon at the address step.

## Metrics

- **Primary metric:** converted (binary), higher is better.
- **Baseline:** 0.1.
- **Minimum detectable effect:** 0.01 absolute (10.00% relative), i.e. from 0.1 to 0.11.
- **Guardrail:** page_load_ms (continuous), lower is better; tolerated relative harm 0.02.

## Design

- **Randomisation unit:** user_id.
- **Allocation:** 50.0% treatment, 50.0% control.
- **Alpha:** 0.05 (two-sided). **Power:** 0.8.
- **Sample size:** 15,041 control + 15,041 treatment = 30,082 units.
- **Sequential design:** 4 looks, O'Brien-Fleming-type alpha spending. The maximum sample is 1.0196 times the fixed-horizon size (29,502). If the true effect equals the MDE, the experiment stops on average at 82% of the maximum.
- **Duration:** 21 days at the stated traffic; run 21 days to cover whole weeks.

## Looks and boundaries

| Look | Information fraction | Units (total) | Day | Critical value (abs z) | Nominal two-sided alpha | Cumulative alpha spent |
|---|---|---|---|---|---|---|
| 1 | 0.250 | 7,521 | 6 | 4.3326 | 1.47e-05 | 1.47e-05 |
| 2 | 0.500 | 15,041 | 11 | 2.9631 | 0.00305 | 0.00305 |
| 3 | 0.750 | 22,562 | 16 | 2.3590 | 0.0183 | 0.0193 |
| 4 | 1.000 | 30,082 | 21 | 2.0141 | 0.044 | 0.05 |

## Decision rule

1. Validity first: a sample ratio mismatch (p below 0.001), units in both arms, repeated rows per unit, differential missing data or a pre-period imbalance make the result Inconclusive, whatever the effect looks like.
2. Ship if, at any of the 4 planned looks, the repeated confidence interval of the effect on converted (critical value of the look, see the boundary table) lies entirely above zero and every guardrail rules out harm beyond its margin.
3. Do not ship if the repeated confidence interval of the effect on converted (critical value of the look, see the boundary table) lies entirely below zero, or any guardrail shows a statistically significant regression.
4. Otherwise continue to the next planned look; after the final look the result is Inconclusive. There is no futility rule: do not stop early for a flat result.
5. Segment cuts and a novelty check are exploratory or advisory. They never change the recommendation.

## Pre-registration checklist

- [ ] Hypothesis, primary metric (converted) and direction are written down before launch.
- [ ] The randomisation unit is user_id; the analysis table has one row per user_id.
- [ ] Allocation is 50% treatment / 50% control, assigned at random and logged at assignment.
- [ ] Sample size 30,082 units and run length 21 days are fixed in advance; the experiment is not stopped because a result looks significant.
- [ ] Analysis schedule: 4 looks with O'Brien-Fleming-type alpha spending, at the listed sample sizes. No other looks at the primary metric.
- [ ] Guardrails and their margins are fixed: page_load_ms (lower is better, margin 0.02).
- [ ] Outlier handling (for example a winsorisation level) and any pre-period covariate for CUPED are chosen now, not after seeing results.
- [ ] Exposure logging has been checked with an A/A run or an SRM check on a dry run.
- [ ] Segments to be explored are listed now and will be reported as exploratory.
- [ ] Start and end dates cover whole weeks; holidays or launches that overlap are noted.
- [ ] An owner is named for the decision, and what happens for each outcome (Ship, Do not ship, Inconclusive) is agreed.

## Assumptions

- Two-sided test, normal approximation to the binomial.
- Independent units, one observation per randomized unit.
- The number of looks, their timing and the spending function were fixed before the experiment started, and the timing of a look never depends on the results seen so far.
- Test statistics at successive looks have independent increments with information proportional to the number of units (a large-sample result for means and proportions of independent units; the allocation ratio and the outcome variance stay constant).
- Boundaries are two-sided and symmetric (stop for benefit or for harm). There is no futility boundary: not crossing at an interim look means continue, not 'no effect'.
- The boundary is applied as a nominal significance level, 2 * (1 - Phi(c_k)), to the usual p-value and interval at that look (an approximation for t tests in small samples).
- Intervals at a look are repeated confidence intervals: valid at every look, wider than a fixed-horizon interval. After an early stop the point estimate overstates the effect on average; no bias-adjusted estimate is computed.
- Any look outside the plan voids the guarantee; analyse with n_looks (Bonferroni) instead.
- Traffic: a constant 3,000 new eligible user_id per day, of which 50% are enrolled, each counted once. Returning units do not add sample.
- The baseline and (for continuous metrics) the standard deviation are the values supplied; if they are wrong, so are the sample size and the power.
- Looks are equally spaced in sample size. If a look happens at a different size, pass the planned total to the analysis so alpha is spent for the information actually collected.

## Analysis command

```
abcopilot analyze DATA.csv --metric converted --metric-type binary --guardrail page_load_ms:continuous:lower:0.02 --unit-col user_id --expected-share 0.5 --alpha 0.05 --mde 0.01 --sequential obrien-fleming --planned-looks 4 --look LOOK --planned-n 30082
```
