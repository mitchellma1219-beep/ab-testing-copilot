"""Synthetic experiment data with a known ground truth. No real users, no real data.

Used by the examples, the dashboard's built-in scenarios, the demo, the benchmarks and the
tests, so every number they show can be compared with the truth that generated it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

import numpy as np
import pandas as pd

SEGMENTS: tuple[str, ...] = ("desktop", "mobile", "tablet")
SEGMENT_SHARES: tuple[float, ...] = (0.5, 0.4, 0.1)


def make_experiment(
    n: int = 20000, treatment_share: float = 0.5, base_rate: float = 0.10, lift: float = 0.015,
    revenue_effect: float = 0.0, seed: int = 7, *, days: int = 14,
    start_date: str = "2026-01-05", novelty_half_life: float | None = None,
    segment_lifts: Mapping[str, float] | None = None, load_ms_shift: float = 0.0,
    srm_drop: float = 0.0,
) -> pd.DataFrame:
    """One row per user with a known treatment effect.

    Ground truth: the conversion lift is ``lift`` (absolute). With ``novelty_half_life`` the
    lift halves every that many days after ``start_date``; ``segment_lifts`` overrides the lift
    per segment; ``load_ms_shift`` moves the page-load guardrail in treatment; ``srm_drop``
    deletes that share of non-converting control users (a logging bug that breaks the sample
    ratio and biases the comparison).
    """
    if n < 1 or days < 1:
        raise ValueError("n and days must be >= 1")
    if not 0 < treatment_share < 1:
        raise ValueError("treatment_share must be in (0, 1)")
    if not 0 <= srm_drop < 1:
        raise ValueError("srm_drop must be in [0, 1)")
    if novelty_half_life is not None and not novelty_half_life > 0:
        raise ValueError("novelty_half_life must be > 0")
    unknown = set(segment_lifts or {}) - set(SEGMENTS)
    if unknown:
        raise ValueError(f"unknown segment(s) {sorted(unknown)}; choose from {list(SEGMENTS)}")
    rng = np.random.default_rng(seed)
    treat = rng.random(n) < treatment_share
    pre_spend = rng.gamma(2.0, 10.0, n)
    u_convert = rng.random(n)
    revenue = 0.8 * pre_spend + rng.normal(0, 8, n) + revenue_effect * treat
    load_ms = rng.normal(1200, 150, n) + load_ms_shift * treat
    day = rng.integers(0, days, n)
    segment = rng.choice(np.array(SEGMENTS), size=n, p=np.array(SEGMENT_SHARES))
    unit_lift = np.full(n, float(lift))
    for name, value in (segment_lifts or {}).items():
        unit_lift[segment == name] = value
    if novelty_half_life is not None:
        unit_lift = unit_lift * 0.5 ** (day / novelty_half_life)
    converted = u_convert < base_rate + unit_lift * treat
    dates = pd.Timestamp(start_date) + pd.to_timedelta(day, unit="D")
    df = pd.DataFrame({
        "user_id": np.arange(n), "variant": np.where(treat, "treatment", "control"),
        "converted": converted.astype(int), "revenue": revenue.round(2),
        "pre_spend": pre_spend.round(2), "page_load_ms": load_ms.round(1),
        "exposure_date": dates.strftime("%Y-%m-%d"), "segment": segment,
    })
    if srm_drop:
        lost = (~treat) & (~converted) & (rng.random(n) < srm_drop)
        df = df[~lost].reset_index(drop=True)
    return df


def make_sessions(
    n_users: int = 4000, treatment_share: float = 0.5, mean_sessions: float = 5.0,
    base_ctr: float = 0.10, ctr_lift: float = 0.0, seed: int = 11,
) -> pd.DataFrame:
    """One row per session, several sessions per user, users randomised.

    Users differ in their click propensity, so sessions of the same user are correlated and a
    session-level test understates the standard error. Ground truth for the ratio metric
    ``sum(clicks) / sum(impressions)``: ``base_ctr`` in control, ``base_ctr + ctr_lift`` in
    treatment.
    """
    if n_users < 2 or mean_sessions < 1:
        raise ValueError("n_users must be >= 2 and mean_sessions >= 1")
    if not (0 < base_ctr < 1 and 0 < base_ctr + ctr_lift < 1):
        raise ValueError("base_ctr and base_ctr + ctr_lift must lie in (0, 1)")
    rng = np.random.default_rng(seed)
    treat = rng.random(n_users) < treatment_share
    n_sessions = 1 + rng.poisson(mean_sessions - 1, n_users)
    propensity = rng.beta(2.0, 2.0 * (1 - base_ctr) / base_ctr, n_users)
    propensity = np.clip(propensity + ctr_lift * treat, 0.0, 1.0)
    user = np.repeat(np.arange(n_users), n_sessions)
    impressions = rng.integers(5, 21, size=user.size)
    clicks = rng.binomial(impressions, propensity[user])
    return pd.DataFrame({
        "user_id": user, "variant": np.where(treat[user], "treatment", "control"),
        "session_id": np.arange(user.size), "impressions": impressions, "clicks": clicks,
    })


class Scenario(NamedTuple):
    """A built-in dataset for the dashboard and the demo, with what is true about it."""

    title: str
    truth: str
    kwargs: Mapping[str, object]


SCENARIOS: dict[str, Scenario] = {
    "clean_win": Scenario(
        "Clean win", "Conversion lift of +1.5 pp, no guardrail effect, valid randomisation.",
        {}),
    "no_effect": Scenario(
        "No effect", "The treatment does nothing. The honest answer is Inconclusive.",
        {"lift": 0.0}),
    "guardrail_regression": Scenario(
        "Guardrail regression",
        "Conversion lift of +1.5 pp, but pages load 60 ms slower in treatment.",
        {"load_ms_shift": 60.0}),
    "sample_ratio_mismatch": Scenario(
        "Sample ratio mismatch",
        "A logging bug loses 15% of non-converting control users. The apparent win is an "
        "artefact and must not be trusted.",
        {"lift": 0.0, "srm_drop": 0.15}),
    "novelty_decay": Scenario(
        "Novelty decay",
        "The lift starts at +6 pp and halves every 3 days: early enthusiasm that fades.",
        {"lift": 0.06, "novelty_half_life": 3.0, "n": 40000}),
    "segment_heterogeneity": Scenario(
        "Segment heterogeneity",
        "The lift is +3 pp on mobile and zero on desktop and tablet.",
        {"lift": 0.0, "segment_lifts": {"mobile": 0.03}, "n": 40000}),
}


def make_scenario(name: str, seed: int = 7) -> pd.DataFrame:
    """Data for one of the built-in scenarios."""
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario '{name}'; choose from {sorted(SCENARIOS)}")
    return make_experiment(seed=seed, **SCENARIOS[name].kwargs)  # type: ignore[arg-type]
