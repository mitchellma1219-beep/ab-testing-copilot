# Decision report: segment heterogeneity

**Recommendation: Ship**  
Evidence quality: **strong**  
Confidence level for the primary metric: 95.0%

## Why

- The primary metric improved: converted effect +0.008485 (95.0% CI [0.002456, 0.01451]).

## Effects

| Metric | Control | Treatment | Absolute effect [CI] | Relative effect [CI] | p | n (C / T) |
|---|---|---|---|---|---|---|
| converted | 0.10158 | 0.11007 | +0.0084852 [+0.002456, +0.014514] | +8.35% [+2.18%, +14.53%] | 0.005804 | 20,112 / 19,888 |

Primary method: two-proportion z test (pooled SE); Wald CI (unpooled SE); delta-method relative CI.

## Diagnostics

- **OK** `sample_ratio_mismatch` — Observed treatment share 0.4972 vs planned 0.5000 (chi-square p = 0.263). No evidence of SRM.
- **OK** `peeking` — Single planned analysis (fixed horizon).
- **OK** `segments_exploratory` — Exploratory segment analysis: 3 segment(s) of 'segment' analysed. Cochran's Q = 24.93 on 2 df, p = 3.86e-06, I^2 = 92%: the absolute effect appears to differ between segments. 1 segment(s) significant after holm correction (family-wise error 0.05). These are hypotheses for a follow-up experiment, not findings; they do not change the recommendation.

## Segments (exploratory)

> Exploratory - hypothesis-generating only. Segment results do not change the recommendation and need a new, pre-registered experiment to be confirmed.

| segment | n (C / T) | Effect | Simultaneous 95.0% CI | p | Adjusted p (holm) |
|---|---|---|---|---|---|
| desktop | 10,044 / 10,023 | +0.00060372 | [-0.0094441, +0.010652] | 0.8856 | 0.8856 |
| mobile | 8,067 / 7,813 | +0.026247 | [+0.01409, +0.038404] | 2.31e-07 | 6.931e-07 |
| tablet | 2,001 / 2,052 | -0.020938 | [-0.044136, +0.0022607] | 0.03063 | 0.06127 |

Heterogeneity (Cochran's Q): Q = 24.93 on 2 df, p = 3.86e-06, I^2 = 92%.

## Assumptions

- Units were randomly assigned and analysed as assigned (intention to treat).
- One independent observation per randomised unit.
- Two-sided tests; guardrails are not corrected for multiplicity (conservative for harm).
- Segment or exploratory cuts are hypothesis-generating, not confirmatory.
