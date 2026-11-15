"""Hostile and malformed inputs. Each case must fail loudly or be flagged, never mislead."""

import numpy as np
import pandas as pd
import pytest

from ab_testing_copilot.cli import main
from ab_testing_copilot.experiment import ExperimentConfig, MetricSpec, analyze_experiment
from ab_testing_copilot.models import Decision

BIN = ExperimentConfig(primary=MetricSpec(column="converted", type="binary"))
REV = ExperimentConfig(primary=MetricSpec(column="revenue", type="continuous"))


def _diag(report, name):
    return next(d for d in report.diagnostics if d.name == name)


def test_srm_invalidates_an_apparent_win(make_df):
    df = make_df(lift=0.03)
    drop = df[(df.variant == "control") & (df.converted == 0)].sample(frac=0.15, random_state=0)
    r = analyze_experiment(df.drop(drop.index), BIN)
    assert r.primary.p_value < 0.001  # naive analysis would look like a clear win
    assert r.decision is Decision.INCONCLUSIVE and r.evidence_quality == "invalid"
    assert not _diag(r, "sample_ratio_mismatch").passed


def test_wrong_unit_of_analysis_is_refused(make_df):
    df = make_df(n=2000, lift=0.0)
    sessions = pd.concat([df] * 8, ignore_index=True)  # 8 perfectly correlated rows per user
    cfg = BIN.model_copy(update={"unit_col": "user_id"})
    r = analyze_experiment(sessions, cfg)
    assert r.decision is Decision.INCONCLUSIVE and not _diag(r, "unit_of_analysis").passed
    # SRM is computed on units, not on inflated row counts
    assert _diag(r, "sample_ratio_mismatch").passed


def test_contaminated_units_are_blocking(make_df):
    df = make_df(n=4000)
    leak = df[df.variant == "control"].head(200).assign(variant="treatment")
    r = analyze_experiment(pd.concat([df, leak]), BIN.model_copy(update={"unit_col": "user_id"}))
    assert r.evidence_quality == "invalid" and not _diag(r, "contamination").passed


def test_single_whale_is_flagged_not_shipped_as_strong(make_df):
    df = make_df(n=4000, rev_effect=0.0)
    df.loc[df[df.variant == "treatment"].index[0], "revenue"] = 5_000_000
    r = analyze_experiment(df, REV)
    assert not _diag(r, "outliers_treatment").passed
    assert r.decision is not Decision.SHIP and r.evidence_quality == "weak"


def test_differential_missingness_blocks(make_df):
    df = make_df(n=10000)
    idx = df[(df.variant == "treatment") & (df.converted == 0)].sample(frac=0.2, random_state=1)
    df["converted"] = df["converted"].astype(float)
    df.loc[idx.index, "converted"] = np.nan
    r = analyze_experiment(df, BIN)
    assert r.evidence_quality == "invalid" and not _diag(r, "missing_data_converted").passed


def test_random_missingness_only_warns(make_df):
    df = make_df(n=10000, lift=0.03)
    df["converted"] = df["converted"].astype(float)
    df.loc[df.sample(frac=0.02, random_state=2).index, "converted"] = np.nan
    r = analyze_experiment(df, BIN)
    assert _diag(r, "missing_data_converted").severity == "warning"
    assert r.decision is Decision.SHIP and r.evidence_quality == "strong"
    # heavy but balanced loss keeps the estimate and downgrades the evidence rating
    df.loc[df.sample(frac=0.2, random_state=3).index, "converted"] = np.nan
    heavy = analyze_experiment(df, BIN)
    assert heavy.decision is Decision.SHIP and heavy.evidence_quality == "weak"


def test_imbalanced_covariate_blocks(make_df):
    df = make_df(n=6000)
    df.loc[df.variant == "treatment", "pre_spend"] += 8
    r = analyze_experiment(df, REV.model_copy(update={"covariate_col": "pre_spend"}))
    assert r.evidence_quality == "invalid" and not _diag(r, "covariate_balance").passed


def test_covariate_with_missing_values_skips_cuped(make_df):
    df = make_df(n=3000)
    df.loc[0, "pre_spend"] = np.nan
    r = analyze_experiment(df, REV.model_copy(update={"covariate_col": "pre_spend"}))
    assert "CUPED" not in r.primary.method and not _diag(r, "cuped").passed


def test_binary_metric_with_other_values_is_rejected(make_df):
    df = make_df(n=500)
    df.loc[0, "converted"] = 7
    with pytest.raises(ValueError, match="other than 0/1"):
        analyze_experiment(df, BIN)


@pytest.mark.parametrize("mutate, match", [
    (lambda d: d.drop(columns=["converted"]), "missing required column"),
    (lambda d: d.assign(converted=d.converted.astype(str)), "must be numeric"),
    (lambda d: d[d.variant == "control"], "at least 2 rows"),
    (lambda d: d.iloc[0:0], "at least 2 rows"),
    (lambda d: d.assign(variant="A"), "at least 2 rows"),
])
def test_structural_problems_raise(make_df, mutate, match):
    with pytest.raises(ValueError, match=match):
        analyze_experiment(mutate(make_df(n=500)), BIN)


def test_infinite_and_all_missing_metric(make_df):
    df = make_df(n=500)
    with pytest.raises(ValueError, match="infinite"):
        analyze_experiment(df.assign(revenue=np.where(df.index == 3, np.inf, df.revenue)), REV)
    with pytest.raises(ValueError, match="fewer than 2"):
        analyze_experiment(df.assign(revenue=np.nan), REV)


def test_extra_variant_labels_are_reported(make_df):
    df = make_df(n=3000)
    df.loc[:99, "variant"] = "holdout"
    r = analyze_experiment(df, BIN)
    assert "100 row(s)" in _diag(r, "unexpected_variants").message


def test_tiny_sample_warns_and_is_weak():
    df = pd.DataFrame({"variant": ["control"] * 6 + ["treatment"] * 6,
                       "converted": [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 0]})
    r = analyze_experiment(df, BIN)
    assert r.evidence_quality == "weak" and any("below 5" in w for w in r.primary.warnings)


def test_config_rejects_unknown_fields_and_bad_values():
    with pytest.raises(ValueError):
        ExperimentConfig(primary=MetricSpec(column="x", type="binary"), alpha=1.5)
    with pytest.raises(ValueError):
        ExperimentConfig(primary=MetricSpec(column="x", type="binary"), n_looks=0)
    with pytest.raises(ValueError):
        ExperimentConfig(primary=MetricSpec(column="x", type="binary"), surprise=1)  # type: ignore[call-arg]


@pytest.mark.parametrize("content", [b"", b"\x00\xff\xfe garbage \x80", b"a,b\n1,2\n",
                                     b'variant,converted\n"control,1\n'])
def test_cli_survives_malformed_files(tmp_path, content, capsys):
    p = tmp_path / "bad.csv"
    p.write_bytes(content)
    assert main(["analyze", str(p), "--metric", "converted", "--metric-type", "binary"]) == 1
    assert "error:" in capsys.readouterr().err


def test_cli_rejects_non_csv_and_row_limit(tmp_path, make_df, monkeypatch, capsys):
    p = tmp_path / "data.pkl"
    p.write_bytes(b"not a pickle we would ever load")
    assert main(["analyze", str(p), "--metric", "converted", "--metric-type", "binary"]) == 1
    import ab_testing_copilot.cli as cli
    monkeypatch.setattr(cli, "MAX_ROWS", 100)
    q = tmp_path / "big.csv"
    make_df(n=500).to_csv(q, index=False)
    assert main(["analyze", str(q), "--metric", "converted", "--metric-type", "binary"]) == 1
    assert "ABCOPILOT_MAX_ROWS" in capsys.readouterr().err
