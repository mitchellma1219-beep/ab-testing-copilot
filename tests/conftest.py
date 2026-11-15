from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def make_df():
    def _make(n=20000, lift=0.02, base=0.10, share=0.5, rev_effect=0.0, seed=1) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        treat = rng.random(n) < share
        pre = rng.gamma(2.0, 10.0, n)
        return pd.DataFrame({
            "user_id": np.arange(n),
            "variant": np.where(treat, "treatment", "control"),
            "converted": (rng.random(n) < base + lift * treat).astype(int),
            "revenue": 0.8 * pre + rng.normal(0, 8, n) + rev_effect * treat,
            "pre_spend": pre,
            "page_load_ms": rng.normal(1200, 150, n),
        })
    return _make
