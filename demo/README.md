# Demo

Everything here is generated from seeded synthetic data with a known ground truth. No real
users, no network.

```bash
pip install -e ".[dev,ui]"
python demo/run_demo.py            # rewrites demo/output/ (about 20 seconds)
streamlit run app/streamlit_app.py # the interactive dashboard
```

## What `run_demo.py` writes

| File in `output/` | What it shows | Ground truth of the data |
|---|---|---|
| `report_clean_win.md`, `.json` | Full report: effect, guardrail, novelty check, exploratory segments, A/A check | Lift +1.5 pp, nothing else |
| `report_sample_ratio_mismatch.md` | A significant-looking loss refused because the sample ratio is broken | No effect; 15% of non-converting control users lost, which inflates the control rate |
| `report_novelty_decay.md` | Ship with weak evidence and a novelty warning | Lift starts at +6 pp and halves every 3 days |
| `report_segment_heterogeneity.md` | Segment effects, labelled exploratory | Lift +3 pp on mobile only |
| `report_sequential_look2.md`, `report_sequential_look3.md` | A pre-registered four-look design: held back at look 2, stopped at look 3 | Lift +3 pp |
| `report_ratio_metric.md` | Sessions aggregated to users, click-through rate by the delta method | CTR lift +2 pp |
| `experiment_plan.md` | Output of the planner for a four-look design | n/a |
| `validation_suite.md` | The 24 Monte Carlo checks at 5,000 simulations, seed 0 | n/a |
| `charts/index.html` | Nine standalone charts, each with a table view | as above |

The chart pages work offline. `charts/plotly.min.js` is the Plotly.js bundle that ships
inside the `plotly` Python package (MIT licence); it is written once and shared by all pages.

## Five-minute walkthrough

1. **Plan.** `abcopilot plan --metric converted` stops and lists the fourteen inputs it will
   not guess. Supply them (see `output/experiment_plan.md`) and it returns sample size,
   duration, look schedule, decision rule and a pre-registration checklist.
2. **A clean result.** Open the dashboard. The default scenario ships: the effect and its
   interval are on *Statistical results*, every check on *Diagnostic warnings*.
3. **A result that only looks clean.** Switch the scenario to *Sample ratio mismatch*. The
   treatment does nothing, yet the naive effect is a "significant" loss of 1.9 points
   (p = 0.00002). The recommendation is Inconclusive with evidence quality *invalid*, and
   the report says what to investigate. With the default seed this scenario also raises
   a novelty warning although the generator has no time trend: a chance alarm, and the
   reason that check is worded as a warning and never as proof.
4. **Looking early.** In *Experiment setup* choose *Pre-registered sequential design*, four
   looks, look 2. A z of 2.8 no longer ships: the boundary at that look is 2.96. The
   *Simulation* tab shows why: repeating a fixed 5% test five times rejects about 14% of
   null experiments, the spending boundaries about 5%.
5. **What the pooled number hides.** *Novelty decay* ships with weak evidence and a warning
   that the effect is fading; *Segment heterogeneity* shows a mobile-only effect, labelled
   exploratory, that does not change the recommendation.
6. **Export.** The *Export* tab downloads the report as Markdown and as JSON.

## Screenshots

`screenshots/` holds seven captures of the dashboard (1440 x 1000, light theme), taken with
`capture_screenshots.cjs` against the built-in scenarios. That script is an optional helper
that needs Node.js, Playwright and Chrome; it is not part of the test suite.
