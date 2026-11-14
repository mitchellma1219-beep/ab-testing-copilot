# Decision report: clean win

**Recommendation: Ship**  
Evidence quality: **strong**  
Confidence level for the primary metric: 95.0%

## Why

- The primary metric improved: converted effect +0.01195 (95.0% CI [0.003485, 0.02041]).
- page_load_ms: harm larger than the 0.02 relative margin is ruled out (worst case 0.001766).

## Effects

| Metric | Control | Treatment | Absolute effect [CI] | Relative effect [CI] | p | n (C / T) |
|---|---|---|---|---|---|---|
| converted | 0.098076 | 0.11002 | +0.011948 [+0.0034845, +0.020412] | +12.18% [+3.04%, +21.32%] | 0.005648 | 10,084 / 9,916 |
| page_load_ms | 1201.6 | 1199.5 | -2.0226 [-6.171, +2.1257] | -0.17% [-0.51%, +0.18%] | 0.3392 | 10,084 / 9,916 |

Primary method: two-proportion z test (pooled SE); Wald CI (unpooled SE); delta-method relative CI.

## Guardrails

- **PASS** — page_load_ms: harm larger than the 0.02 relative margin is ruled out (worst case 0.001766).

## Diagnostics

- **OK** `sample_ratio_mismatch` — Observed treatment share 0.4958 vs planned 0.5000 (chi-square p = 0.235). No evidence of SRM.
- **OK** `peeking` — Single planned analysis (fixed horizon).
- **OK** `novelty_effect` — No clear time trend in the treatment effect: slope +0.002154 per day (SE 0.00107, t = 2.01 on 12 df, p = 0.0669) over 14 periods; fitted effect -0.002642 at the start and +0.02536 at the end; first-half effect +0.00465 (SE 0.00612) vs second-half +0.01856 (SE 0.00605). The check has limited power, so this does not rule out a novelty effect.
- **OK** `segments_exploratory` — Exploratory segment analysis: 3 segment(s) of 'segment' analysed. Cochran's Q = 0.42 on 2 df, p = 0.81, I^2 = 0%: no clear evidence that the absolute effect differs. 0 segment(s) significant after holm correction (family-wise error 0.05). These are hypotheses for a follow-up experiment, not findings; they do not change the recommendation.
- **OK** `aa_check` — A/A check: 1000 random re-labellings of 20,000 'user_id' unit(s), two-proportion z test on rows: 3.7% came out significant at alpha = 0.05 (95% interval 2.6% to 5.1%, binomial p = 0.0591). The false-positive rate is consistent with alpha.

## Effect over time (novelty check)

| Period | n (C / T) | Effect | SE |
|---|---|---|---|
| 2026-01-05 | 734 / 659 | +0.0046619 | 0.0168 |
| 2026-01-06 | 694 / 719 | -0.0068399 | 0.0169 |
| 2026-01-07 | 733 / 635 | -0.0052035 | 0.0167 |
| 2026-01-08 | 763 / 726 | +0.010786 | 0.0162 |
| 2026-01-09 | 644 / 752 | -0.00031386 | 0.0164 |
| 2026-01-10 | 769 / 721 | -0.0081558 | 0.0142 |
| 2026-01-11 | 773 / 702 | +0.042446 | 0.0168 |
| 2026-01-12 | 708 / 701 | +0.013826 | 0.0164 |
| 2026-01-13 | 680 / 744 | +0.0077324 | 0.017 |
| 2026-01-14 | 749 / 709 | +0.036001 | 0.0161 |
| 2026-01-15 | 731 / 754 | +0.001016 | 0.0154 |
| 2026-01-16 | 714 / 697 | +0.015338 | 0.0165 |
| 2026-01-17 | 685 / 734 | +0.035804 | 0.0154 |
| 2026-01-18 | 707 / 663 | +0.018831 | 0.0154 |

## Segments (exploratory)

> Exploratory - hypothesis-generating only. Segment results do not change the recommendation and need a new, pre-registered experiment to be confirmed.

| segment | n (C / T) | Effect | Simultaneous 95.0% CI | p | Adjusted p (holm) |
|---|---|---|---|---|---|
| desktop | 4,983 / 4,934 | +0.0091234 | [-0.005733, +0.02398] | 0.1415 | 0.283 |
| mobile | 4,058 / 4,002 | +0.014325 | [-0.0018353, +0.030484] | 0.0338 | 0.1014 |
| tablet | 1,043 / 980 | +0.015936 | [-0.015628, +0.047501] | 0.2259 | 0.283 |

Heterogeneity (Cochran's Q): Q = 0.42 on 2 df, p = 0.81, I^2 = 0%.

## Assumptions

- Units were randomly assigned and analysed as assigned (intention to treat).
- One independent observation per randomised unit.
- Two-sided tests; guardrails are not corrected for multiplicity (conservative for harm).
- Segment or exploratory cuts are hypothesis-generating, not confirmatory.
