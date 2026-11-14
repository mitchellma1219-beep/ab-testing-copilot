# Methodology

| Area | Method | Notes |
|---|---|---|
| Binary metric test | Two-proportion z test, pooled SE | Equivalent to the uncorrected 2x2 chi-square test |
| Binary metric CI | Wald interval, unpooled SE | Warns when any cell count < 5 |
| Continuous metric | Welch t test | No equal-variance assumption |
| Relative lift CI | Delta method on t/c - 1 | Undefined when the control value <= 0 |
| Skewed metrics | Percentile bootstrap (`bootstrap_mean_diff`) | Python API; compare with Welch |
| CUPED | y - theta (x - mean x), theta pooled within arm | Covariate must be pre-assignment |
| Multiplicity | Bonferroni, Holm (FWER), Benjamini-Hochberg (FDR) | `adjust_pvalues` |
| Sample size | Normal approximation, two-sided, unequal allocation supported | Fixed horizon |
| SRM | Chi-square goodness of fit, flagged at p < 0.001 | Blocking |
| Peeking | Bonferroni alpha / looks on the primary metric | Conservative; not a group-sequential design |
| Guardrails | Non-inferiority on the relative effect | fail / pass / uncertain |

## Decision rule

1. Any blocking diagnostic (SRM, contamination, repeated units, differential missingness,
   covariate imbalance) -> Inconclusive, evidence "invalid".
2. A guardrail with a significant regression -> Do not ship.
3. Primary CI entirely on the harmful side -> Do not ship.
4. Primary CI entirely on the beneficial side -> Ship, unless a guardrail is "uncertain"
   (then Inconclusive by default).
5. Otherwise Inconclusive, with a statement on whether the MDE is still inside the CI.

## Limitations

- No group-sequential (alpha-spending) or always-valid inference.
- No cluster-robust or ratio-metric (delta method on per-unit ratios) analysis: repeated
  rows per unit are refused rather than modelled.
- Missing data are dropped under an MCAR assumption; differential missingness blocks.
- Novelty effects and heterogeneous treatment effects are not estimated in this version.
