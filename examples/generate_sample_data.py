"""Generate synthetic experiment data with a known ground truth (no real users)."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def make_experiment(
    n: int = 20000, treatment_share: float = 0.5, base_rate: float = 0.10, lift: float = 0.015,
    revenue_effect: float = 0.0, seed: int = 7,
) -> pd.DataFrame:
    """Ground truth: conversion lift = ``lift`` (absolute); page-load guardrail unaffected."""
    rng = np.random.default_rng(seed)
    treat = rng.random(n) < treatment_share
    pre_spend = rng.gamma(2.0, 10.0, n)
    converted = rng.random(n) < base_rate + lift * treat
    revenue = 0.8 * pre_spend + rng.normal(0, 8, n) + revenue_effect * treat
    load_ms = rng.normal(1200, 150, n)
    return pd.DataFrame({
        "user_id": np.arange(n), "variant": np.where(treat, "treatment", "control"),
        "converted": converted.astype(int), "revenue": revenue.round(2),
        "pre_spend": pre_spend.round(2), "page_load_ms": load_ms.round(1),
    })


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "sample_experiment.csv")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    make_experiment(seed=a.seed).to_csv(a.out, index=False)
    print(f"wrote {a.out}")
