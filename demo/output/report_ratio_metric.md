# Decision report: click-through rate as a ratio metric

**Recommendation: Ship**  
Evidence quality: **strong**  
Confidence level for the primary metric: 95.0%

## Why

- The primary metric improved: clicks/impressions effect +0.02077 (95.0% CI [0.01668, 0.02486]).

## Effects

| Metric | Control | Treatment | Absolute effect [CI] | Relative effect [CI] | p | n (C / T) |
|---|---|---|---|---|---|---|
| clicks/impressions | 0.099033 | 0.1198 | +0.020772 [+0.016682, +0.024861] | +20.97% [+16.41%, +25.54%] | 2.372e-23 | 2,994 / 3,006 |

Primary method: delta-method z test on unit-level sums; delta-method relative CI.

## Diagnostics

- **OK** `sample_ratio_mismatch` — Observed treatment share 0.5010 vs planned 0.5000 (chi-square p = 0.877). No evidence of SRM.
- **OK** `peeking` — Single planned analysis (fixed horizon).
- **OK** `outliers_control` — control: 0 value(s) beyond 10 robust SDs; top 1% of units hold 5% of the total. No dominant outliers.
- **OK** `outliers_treatment` — treatment: 0 value(s) beyond 10 robust SDs; top 1% of units hold 4% of the total. No dominant outliers.
- **OK** `aa_check` — A/A check: 1000 random re-labellings of 6,000 'user_id' unit(s), delta-method z test on unit-level sums: 6.1% came out significant at alpha = 0.05 (95% interval 4.7% to 7.8%, binomial p = 0.11). The false-positive rate is consistent with alpha.

## Assumptions

- Units were randomly assigned and analysed as assigned (intention to treat).
- One independent observation per randomised unit.
- Two-sided tests; guardrails are not corrected for multiplicity (conservative for harm).
- Segment or exploratory cuts are hypothesis-generating, not confirmatory.
