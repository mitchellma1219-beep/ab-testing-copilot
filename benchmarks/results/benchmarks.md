| Operation | Best | Median | Peak additional memory |
|---|---|---|---|
| analyze_experiment, 10,000 rows: CUPED + 1 guardrail | 11.2 ms | 12.1 ms | 2 MB |
| analyze_experiment, 100,000 rows: CUPED + 1 guardrail | 37.7 ms | 38.7 ms | 12 MB |
| analyze_experiment, 1,000,000 rows: CUPED + 1 guardrail | 333.9 ms | 335.6 ms | 116 MB |
| analyze_experiment, 100,000 rows: sequential look + novelty + segments | 124.9 ms | 127.2 ms | 17 MB |
| sequential_boundaries, 5 looks (O'Brien-Fleming type) | 4.2 ms | 4.5 ms | not measured |
| sequential_boundaries, 20 looks (O'Brien-Fleming type) | 39.0 ms | 39.8 ms | not measured |
| sequential_boundaries, 100 looks (O'Brien-Fleming type) | 685.9 ms | 688.6 ms | not measured |
| inflation_factor, 5 looks (Pocock type, power 0.8) | 25.2 ms | 26.6 ms | not measured |
| aa_check, 1,000 re-labellings of 20,000 units (binary) | 470.4 ms | 636.2 ms | not measured |
| aggregate_to_units, 999,801 session rows -> 200,000 users | 178.2 ms | 180.2 ms | 83 MB |
| analyze_experiment, ratio metric (delta method), 200,000 users | 62.4 ms | 64.3 ms | 24 MB |
| bootstrap_mean_diff, 2,000 resamples x 100,000 per arm | 1.80 s | 1.90 s | not measured |
| run_validation_suite, 5,000 simulations (24 checks) | 14.04 s | 14.14 s | not measured |

3 run(s) per operation. Python 3.13.18, numpy 2.5.4, scipy 1.18.1, pandas 3.1.1, 2 CPU(s), Linux-6.18.44-fc-v470-x86_64-with-glibc2.39.
