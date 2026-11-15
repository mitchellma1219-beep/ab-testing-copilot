# Decision report: novelty decay

**Recommendation: Ship**  
Evidence quality: **weak**  
Confidence level for the primary metric: 95.0%

## Why

- The primary metric improved: converted effect +0.01663 (95.0% CI [0.0105, 0.02276]).
- Possible novelty effect: the treatment effect shrinks towards zero over time, so the pooled estimate may overstate the lasting effect. Evidence: slope -0.004444 per day (SE 0.000775, t = -5.73 on 12 df, p = 9.41e-05) over 14 periods; fitted effect +0.04551 at the start and -0.01226 at the end; first-half effect +0.03323 (SE 0.00454) vs second-half -0.0004649 (SE 0.00427). This is a warning, not proof: a changing mix of units over time, seasonality or chance produce the same pattern. Consider running longer or re-testing on a later cohort.

## Effects

| Metric | Control | Treatment | Absolute effect [CI] | Relative effect [CI] | p | n (C / T) |
|---|---|---|---|---|---|---|
| converted | 0.10158 | 0.11821 | +0.016631 [+0.010502, +0.02276] | +16.37% [+9.86%, +22.88%] | 1.047e-07 | 20,112 / 19,888 |

Primary method: two-proportion z test (pooled SE); Wald CI (unpooled SE); delta-method relative CI.

## Diagnostics

- **OK** `sample_ratio_mismatch` — Observed treatment share 0.4972 vs planned 0.5000 (chi-square p = 0.263). No evidence of SRM.
- **OK** `peeking` — Single planned analysis (fixed horizon).
- **WARNING** `novelty_effect` — Possible novelty effect: the treatment effect shrinks towards zero over time, so the pooled estimate may overstate the lasting effect. Evidence: slope -0.004444 per day (SE 0.000775, t = -5.73 on 12 df, p = 9.41e-05) over 14 periods; fitted effect +0.04551 at the start and -0.01226 at the end; first-half effect +0.03323 (SE 0.00454) vs second-half -0.0004649 (SE 0.00427). This is a warning, not proof: a changing mix of units over time, seasonality or chance produce the same pattern. Consider running longer or re-testing on a later cohort.

## Effect over time (novelty check)

| Period | n (C / T) | Effect | SE |
|---|---|---|---|
| 2026-01-05 | 1,478 / 1,440 | +0.049152 | 0.0122 |
| 2026-01-06 | 1,359 / 1,472 | +0.027137 | 0.0126 |
| 2026-01-07 | 1,480 / 1,419 | +0.029959 | 0.0121 |
| 2026-01-08 | 1,435 / 1,445 | +0.018644 | 0.0119 |
| 2026-01-09 | 1,381 / 1,469 | +0.048226 | 0.012 |
| 2026-01-10 | 1,467 / 1,400 | +0.024114 | 0.0118 |
| 2026-01-11 | 1,381 / 1,421 | +0.035535 | 0.0116 |
| 2026-01-12 | 1,466 / 1,400 | +0.011284 | 0.0116 |
| 2026-01-13 | 1,376 / 1,404 | +0.023858 | 0.0114 |
| 2026-01-14 | 1,503 / 1,327 | -0.0041911 | 0.0117 |
| 2026-01-15 | 1,463 / 1,466 | +0.0025313 | 0.011 |
| 2026-01-16 | 1,429 / 1,423 | -0.0094105 | 0.0111 |
| 2026-01-17 | 1,469 / 1,342 | -0.015837 | 0.0113 |
| 2026-01-18 | 1,425 / 1,460 | -0.010007 | 0.0111 |

## Assumptions

- Units were randomly assigned and analysed as assigned (intention to treat).
- One independent observation per randomised unit.
- Two-sided tests; guardrails are not corrected for multiplicity (conservative for harm).
- Segment or exploratory cuts are hypothesis-generating, not confirmatory.
