# Methodology

What each command computes, what it assumes and where it stops. Verification evidence for
every method is in `QUALITY_REPORT.md` at the repository root.

## Methods at a glance

| Area | Method | Notes |
|---|---|---|
| Binary metric test | Two-proportion z test, pooled SE | Equivalent to the uncorrected 2x2 chi-square test |
| Binary metric CI | Wald interval, unpooled SE | Warns when any cell count < 5 |
| Continuous metric | Welch t test | No equal-variance assumption |
| Ratio metric | Delta method on unit-level sums, normal reference | `sum(x) / sum(d)` over randomised units |
| Relative lift CI | Delta method on t/c - 1 | Undefined when the control value <= 0 |
| Skewed metrics | Percentile bootstrap (`bootstrap_mean_diff`) | Python API; compare with Welch |
| CUPED | y - theta (x - mean x), theta pooled within arm | Covariate must be pre-assignment; not for ratio metrics |
| Multiplicity | Bonferroni, Holm (FWER), Benjamini-Hochberg (FDR) | `adjust_pvalues` |
| Sample size, power, MDE | Normal approximation, two-sided, unequal allocation supported | Fixed horizon |
| Planned interim looks | Lan-DeMets alpha spending, O'Brien-Fleming type or Pocock type | Two-sided, symmetric, no futility rule |
| Unplanned looks | Bonferroni alpha / looks | Conservative; not a design |
| SRM | Chi-square goodness of fit, flagged at p < 0.001 | Blocking |
| Guardrails | Non-inferiority on the relative effect | fail / pass / uncertain |
| Novelty effect | Weighted trend of per-period effects | Warning with evidence, never proof |
| Segment effects | Per-segment tests, adjusted p-values, Cochran's Q | Exploratory, never feeds the decision |
| A/A check | Random re-labelling of units, binomial test of the rejection rate | Blocking only if inflated |

## Decision rule

1. Any blocking diagnostic (SRM, contamination, repeated rows per unit, differential
   missingness, covariate imbalance, an inflated A/A check) -> Inconclusive, evidence
   "invalid".
2. A guardrail with a significant regression -> Do not ship (even if the harm is inside
   the margin: a regression that is certain is not waved through).
3. Primary interval entirely on the harmful side -> Do not ship.
4. Primary interval entirely on the beneficial side -> Ship, unless a guardrail is
   "uncertain" (then Inconclusive by default).
5. Otherwise Inconclusive. At the single or final analysis the report says whether the
   MDE is still inside the interval; at an interim look it says "continue".

Evidence quality: "invalid" (a blocking check failed), "weak" (a warning failed, for
example unplanned looks, heavy balanced missingness, dominant outliers, a novelty warning,
a final sequential look well short of the planned sample), "moderate" (a guardrail is
uncertain), otherwise "strong". The decision uses the interval, not the p-value; for
proportions the Wald interval (unpooled SE) and the z test (pooled SE) can disagree in
rare borderline cases.

## Group-sequential designs

For K planned looks at information fractions t_1 < ... < t_K = 1, look k rejects when
|Z_k| >= c_k, with c_k solving

    P(|Z_1| < c_1, ..., |Z_{k-1}| < c_{k-1}, |Z_k| >= c_k | no effect) = a(t_k) - a(t_{k-1})

where `a` is the cumulative two-sided alpha spent:

- O'Brien-Fleming type: a(t) = 4 - 4 Phi(z_{alpha/4} / sqrt(t))
- Pocock type: a(t) = alpha ln(1 + (e - 1) t)

These are the Lan and DeMets (1983) functions with alpha / 2 in each tail, the convention
of Stata `gsbounds`, gsDesign and NCSS PASS. The probability is a recursive
one-dimensional integral over the sub-density of the score statistic among paths that have
not stopped (Armitage, McPherson and Rowe 1969), evaluated by composite Gauss-Legendre
quadrature: panels at most one kernel standard deviation wide, 12 nodes each.

- The critical value becomes a nominal two-sided level 2 (1 - Phi(c_k)); the primary
  metric and the guardrails are estimated at that level, so every interval in the report
  is a repeated confidence interval.
- With `planned_sample_size`, alpha is spent for the fraction actually observed
  (observed n / planned n), earlier looks are taken at their planned fractions, and the
  final look spends everything that is left using the observed information ratios. A look
  with less data than the previous planned look is refused.
- Power and the sample-size inflation factor come from the same integral with a drift
  (expected final z); the factor is the ratio of squared drifts needed for equal power.

Assumptions:

1. Looks, their timing and the spending function were fixed before the experiment
   started, and the timing never depends on the results seen so far.
2. Independent increments with information proportional to the number of units: a
   large-sample result for means and proportions of independent units, constant variance
   and allocation.
3. Two-sided symmetric boundaries, no futility boundary. Not crossing means "continue".
4. The nominal level is applied to the usual p-value and interval (an approximation for
   t tests in small samples).
5. After an early stop the point estimate overstates the effect on average. No
   bias-adjusted estimate, stage-wise p-value or adjusted final interval is computed.
6. A look outside the plan voids the guarantee; use `--looks` (Bonferroni) instead.

## Unplanned looks

`--looks K` divides alpha by K for the primary metric. A guardrail regression is still
flagged at the unadjusted level (so harm is not hidden by the penalty), but harm beyond the
margin must be ruled out at the stricter alpha / K level before the guardrail counts as
passed. The evidence rating is "weak".

## Ratio metrics and the unit of analysis

When rows are finer than the randomised unit (sessions of a user), either

- aggregate to one row per unit with `--aggregate COL=how,...` (`sum`, `mean`, `max`,
  `min`, `first`, `unique`; a unit with a missing row value gets a missing aggregate; a
  column `n_rows` is added), or
- analyse `sum(x) / sum(d)` as a ratio metric: Var(R) is approximately
  (var_x - 2 R cov_xd + R^2 var_d) / (n d_bar^2) per arm, with unit-level variances.

Repeated rows per declared unit are refused, not modelled. If no unit column is declared,
clustering cannot be detected.

## Novelty check

Needs a date column: ISO-8601 text, a datetime, or a numeric day count (days are compared
in UTC). One effect estimate per period (a day by default) with at least 50 units per arm;
at least 5 usable periods. A straight line is fitted by weighted least squares (weights
1 / SE^2). The slope standard error is multiplied by sqrt(max(1, residual mean square)) and
tested against a t distribution with n - 2 degrees of freedom, so extra day-to-day variation
widens the test. A significant trend (p < alpha) is

- a **decay** (the warning) if the fitted effect ends closer to zero on the same side, or
  overshoots zero by at most half of its starting size;
- a growth or a reversal otherwise, reported for information.

It assumes one row per unit with the date that unit was first exposed, so periods are
independent. It cannot separate a novelty effect from a changing mix of units over time,
seasonality or chance, and it uses the raw metric even when CUPED is applied to the
primary estimate. It never changes the recommendation; a decay lowers the evidence rating
to "weak".

## Segment effects (exploratory)

Segments with at least 30 units per arm and some variation are tested at alpha; p-values
are adjusted across the analysed segments (Holm by default) and intervals are Bonferroni
simultaneous intervals. Cochran's Q (inverse-variance weights, chi-square with k - 1
degrees of freedom) tests equality of the absolute effect; I^2 is reported. More than 30
levels are not analysed. Segment results are hypotheses for a new, pre-registered
experiment: they are never used for the recommendation or the evidence rating, and they
are not adjusted for interim looks.

## A/A check

Units are re-labelled at random (arm sizes kept) 100 to 20,000 times and the same test is
repeated; every rejection is a false positive. The rejection rate is compared with alpha by
an exact binomial test at the 0.01 level: "inflated" is blocking, "conservative" and
"calibrated" inform. With 1,000 re-labellings only rates above roughly 7% are flagged.

## Experiment plan

`plan` computes sample size, the sequential inflation, duration (constant daily traffic,
each unit counted once), the look schedule, a decision rule and a checklist from stated
inputs. It has no defaults for hypothesis, metric, direction, baseline, MDE and its scale,
alpha, power, allocation, unit, traffic, guardrails or the number of looks, and lists what
is missing instead of filling it in.

## Limitations

- No futility boundaries, no always-valid (anytime) inference, no bias-adjusted estimates
  after sequential stopping.
- No cluster-robust regression: clustering is handled by aggregation or the delta method.
- CUPED is not available for ratio metrics; sample size is not computed for ratio metrics.
- Missing data are dropped under an MCAR assumption; differential missingness blocks.
- Guardrails are not corrected for the number of guardrail metrics.
- One treatment arm against one control; no multi-arm or factorial designs.
- The normal approximations need adequate counts; small-sample warnings are issued, exact
  tests are not implemented.

## References

- Armitage, McPherson, Rowe (1969). Repeated significance tests on accumulating data.
- Lan, DeMets (1983). Discrete sequential boundaries for clinical trials.
- DeMets, Lan (1994). Interim analysis: the alpha spending function approach.
- Jennison, Turnbull (2000). Group Sequential Methods with Applications to Clinical Trials.
- Deng, Xu, Kohavi, Walker (2013). Improving the sensitivity of online controlled
  experiments by utilizing pre-experiment data (CUPED).
- Deng, Knoblich, Lu (2018). Applying the delta method in metric analytics.
- Cochran (1954). The combination of estimates from different experiments.
