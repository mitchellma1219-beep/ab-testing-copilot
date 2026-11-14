# Decision report: sequential design, look 2 of 4

**Recommendation: Inconclusive**  
Evidence quality: **strong**  
Confidence level for the primary metric: 99.70%

## Why

- The interval includes zero: converted effect +0.02509 (99.70% CI [-0.003977, 0.05416]).
- Interim look 2 of 4: the O'Brien-Fleming-type boundary (absolute z of at least 2.963) was not crossed. Continue to the next planned look. This is not evidence of no effect, and the design has no futility rule.

## Effects

| Metric | Control | Treatment | Absolute effect [CI] | Relative effect [CI] | p | n (C / T) |
|---|---|---|---|---|---|---|
| converted | 0.095622 | 0.12072 | +0.025094 [-0.0039767, +0.054164] | +26.24% [-8.00%, +60.48%] | 0.01065 | 1,987 / 2,013 |

Primary method: two-proportion z test (pooled SE); Wald CI (unpooled SE); delta-method relative CI.

## Sequential design

O'Brien-Fleming-type alpha spending, look 2 of 4. At this look the result is significant only if the absolute z statistic reaches 2.9631, i.e. p < 0.00305. Alpha spent so far: 0.00305 of 0.05. Intervals above are repeated confidence intervals.

Planned boundaries:

| Look | Information fraction | Critical value (abs z) | Nominal two-sided alpha | Cumulative alpha spent |
|---|---|---|---|---|
| 1 | 0.250 | 4.3326 | 1.47e-05 | 1.47e-05 |
| 2 (this look) | 0.500 | 2.9631 | 0.00305 | 0.00305 |
| 3 | 0.750 | 2.3590 | 0.0183 | 0.0193 |
| 4 | 1.000 | 2.0141 | 0.044 | 0.05 |

## Diagnostics

- **OK** `sample_ratio_mismatch` — Observed treatment share 0.5032 vs planned 0.5000 (chi-square p = 0.681). No evidence of SRM.
- **OK** `sequential_design` — Pre-registered O'Brien-Fleming-type group-sequential design, look 2 of 4 at information fraction 0.500: significance needs an absolute z of at least 2.9631 (nominal two-sided level 0.00305); alpha spent so far 0.00305 of 0.05.

## Assumptions

- Units were randomly assigned and analysed as assigned (intention to treat).
- One independent observation per randomised unit.
- Two-sided tests; guardrails are not corrected for multiplicity (conservative for harm).
- Segment or exploratory cuts are hypothesis-generating, not confirmatory.
- The number of looks, their timing and the spending function were fixed before the experiment started, and the timing of a look never depends on the results seen so far.
- Test statistics at successive looks have independent increments with information proportional to the number of units (a large-sample result for means and proportions of independent units; the allocation ratio and the outcome variance stay constant).
- Boundaries are two-sided and symmetric (stop for benefit or for harm). There is no futility boundary: not crossing at an interim look means continue, not 'no effect'.
- The boundary is applied as a nominal significance level, 2 * (1 - Phi(c_k)), to the usual p-value and interval at that look (an approximation for t tests in small samples).
- Intervals at a look are repeated confidence intervals: valid at every look, wider than a fixed-horizon interval. After an early stop the point estimate overstates the effect on average; no bias-adjusted estimate is computed.
- Any look outside the plan voids the guarantee; analyse with n_looks (Bonferroni) instead.
- Guardrail intervals use the same sequential critical value as the primary metric, so early looks under an O'Brien-Fleming-type boundary are insensitive to moderate harm.
