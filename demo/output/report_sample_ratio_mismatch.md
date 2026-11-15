# Decision report: sample ratio mismatch

**Recommendation: Inconclusive**  
Evidence quality: **invalid**  
Confidence level for the primary metric: 95.0%

## Why

- The experiment failed validity checks; the effect estimate is not trustworthy and must not be used for a launch decision.
- Observed treatment share 0.5326 vs planned 0.5000 (chi-square p = 6.13e-19). Sample ratio mismatch: assignment or logging is likely broken; effect estimates cannot be trusted until the cause is found.

## Effects

| Metric | Control | Treatment | Absolute effect [CI] | Relative effect [CI] | p | n (C / T) |
|---|---|---|---|---|---|---|
| converted | 0.11364 | 0.094393 | -0.019246 [-0.028054, -0.010438] | -16.94% [-23.96%, -9.91%] | 1.681e-05 | 8,703 / 9,916 |
| page_load_ms | 1201.8 | 1199.5 | -2.2216 [-6.526, +2.0829] | -0.18% [-0.54%, +0.17%] | 0.3117 | 8,703 / 9,916 |

Primary method: two-proportion z test (pooled SE); Wald CI (unpooled SE); delta-method relative CI.

## Guardrails

- **PASS** — page_load_ms: harm larger than the 0.02 relative margin is ruled out (worst case 0.001729).

## Diagnostics

- **BLOCKING** `sample_ratio_mismatch` — Observed treatment share 0.5326 vs planned 0.5000 (chi-square p = 6.13e-19). Sample ratio mismatch: assignment or logging is likely broken; effect estimates cannot be trusted until the cause is found.
- **OK** `peeking` — Single planned analysis (fixed horizon).

## Assumptions

- Units were randomly assigned and analysed as assigned (intention to treat).
- One independent observation per randomised unit.
- Two-sided tests; guardrails are not corrected for multiplicity (conservative for harm).
- Segment or exploratory cuts are hypothesis-generating, not confirmatory.
