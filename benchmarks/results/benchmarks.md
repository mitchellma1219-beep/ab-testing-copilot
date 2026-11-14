| Operation | Best | Median | Peak additional memory |
|---|---|---|---|
| analyze_experiment, 10,000 rows: CUPED + 1 guardrail | 12.3 ms | 12.6 ms | 2 MB |
| analyze_experiment, 100,000 rows: CUPED + 1 guardrail | 37.6 ms | 38.1 ms | 12 MB |
| analyze_experiment, 1,000,000 rows: CUPED + 1 guardrail | 373.5 ms | 420.7 ms | 116 MB |
| analyze_experiment, 100,000 rows: sequential look + novelty + segments | 119.4 ms | 128.7 ms | 17 MB |
| sequential_boundaries, 5 looks (O'Brien-Fleming type) | 3.9 ms | 3.9 ms | not measured |
| sequential_boundaries, 20 looks (O'Brien-Fleming type) | 38.6 ms | 40.5 ms | not measured |
| sequential_boundaries, 100 looks (O'Brien-Fleming type) | 648.0 ms | 691.5 ms | not measured |
| inflation_factor, 5 looks (Pocock type, power 0.8) | 17.4 ms | 18.5 ms | not measured |
| aa_check, 1,000 re-labellings of 20,000 units (binary) | 450.9 ms | 502.6 ms | not measured |
| aggregate_to_units, 999,801 session rows -> 200,000 users | 153.7 ms | 158.9 ms | 83 MB |
| analyze_experiment, ratio metric (delta method), 200,000 users | 62.8 ms | 62.9 ms | 24 MB |
| bootstrap_mean_diff, 2,000 resamples x 100,000 per arm | 1.97 s | 2.22 s | not measured |
| run_validation_suite, 5,000 simulations (24 checks) | 13.37 s | 13.93 s | not measured |

3 run(s) per operation. Python 3.13.18, numpy 2.5.3, scipy 1.18.1, pandas 3.0.5, 2 CPU(s), Linux-6.18.44-fc-v470-x86_64-with-glibc2.39.
