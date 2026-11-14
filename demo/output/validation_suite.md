# Monte Carlo validation suite

`abcopilot simulate --n-sims 5000 --seed 0`

| Check | Estimate | Expected | Tolerance | MC SE | Sims | Result |
|---|---|---|---|---|---|---|
| false_positive_rate[normal] | 0.0454 | 0.0500 | 0.0173 | 0.0031 | 5000 | PASS |
| false_positive_rate[binary] | 0.0524 | 0.0500 | 0.0223 | 0.0031 | 5000 | PASS |
| false_positive_rate[lognormal] | 0.0494 | 0.0500 | 0.0273 | 0.0031 | 5000 | PASS |
| false_positive_rate[normal] | 0.0516 | 0.0500 | 0.0173 | 0.0031 | 5000 | PASS |
| power[normal] | 0.7920 | 0.7982 | 0.0277 | 0.0057 | 5000 | PASS |
| power[binary] | 0.8000 | 0.8000 | 0.0326 | 0.0057 | 5000 | PASS |
| power[binary] | 0.6986 | 0.6870 | 0.0362 | 0.0066 | 5000 | PASS |
| ci_coverage[normal] | 0.9494 | 0.9500 | 0.0173 | 0.0031 | 5000 | PASS |
| ci_coverage[binary] | 0.9446 | 0.9500 | 0.0223 | 0.0031 | 5000 | PASS |
| ci_coverage[lognormal] | 0.9458 | 0.9500 | 0.0273 | 0.0031 | 5000 | PASS |
| peeking_fpr[looks=5,uncorrected] | 0.1430 | n/a | n/a | 0.0111 | 1000 | info |
| peeking_fpr[looks=5,bonferroni] | 0.0400 | 0.0500 | 0.0276 | 0.0069 | 1000 | PASS |
| fwer[m=10,uncorrected] | 0.3880 | 0.4013 | 0.0670 | 0.0155 | 1000 | PASS |
| fwer[m=10,holm] | 0.0410 | 0.0500 | 0.0276 | 0.0069 | 1000 | PASS |
| fwer[m=10,bonferroni] | 0.0540 | 0.0500 | 0.0276 | 0.0069 | 1000 | PASS |
| cuped_variance_ratio[rho=0.7] | 0.5110 | 0.5100 | 0.0865 | 0.0229 | 1000 | PASS |
| sequential_fpr[obrien-fleming,looks=5,normal] | 0.0442 | 0.0500 | 0.0173 | 0.0031 | 5000 | PASS |
| sequential_fpr[pocock,looks=5,normal] | 0.0468 | 0.0500 | 0.0173 | 0.0031 | 5000 | PASS |
| sequential_fpr[obrien-fleming,looks=4,binary] | 0.0552 | 0.0500 | 0.0223 | 0.0031 | 5000 | PASS |
| sequential_power[obrien-fleming,looks=5,normal] | 0.7854 | 0.7884 | 0.0281 | 0.0058 | 5000 | PASS |
| sequential_power[pocock,looks=5,normal] | 0.7192 | 0.7133 | 0.0306 | 0.0064 | 5000 | PASS |
| ratio_false_positive_rate[delta method] | 0.0482 | 0.0500 | 0.0223 | 0.0031 | 5000 | PASS |
| ratio_false_positive_rate[rows as units] | 0.1674 | n/a | n/a | 0.0053 | 5000 | info |
| ratio_ci_coverage[delta method] | 0.9494 | 0.9500 | 0.0223 | 0.0031 | 5000 | PASS |
