"""A/B Testing Copilot: design, diagnose, analyze, simulate and decide on experiments."""

from ab_testing_copilot.analysis import (
    adjust_pvalues,
    bootstrap_mean_diff,
    compare_means,
    compare_proportions,
    cuped_adjust,
)
from ab_testing_copilot.decision import decide
from ab_testing_copilot.design import (
    duration_days,
    mde_for_proportions,
    power_for_means,
    power_for_proportions,
    sample_size_for_means,
    sample_size_for_proportions,
)
from ab_testing_copilot.diagnostics import srm_check
from ab_testing_copilot.experiment import ExperimentConfig, analyze_experiment

__version__ = "0.1.0"

__all__ = [
    "ExperimentConfig",
    "adjust_pvalues",
    "analyze_experiment",
    "bootstrap_mean_diff",
    "compare_means",
    "compare_proportions",
    "cuped_adjust",
    "decide",
    "duration_days",
    "mde_for_proportions",
    "power_for_means",
    "power_for_proportions",
    "sample_size_for_means",
    "sample_size_for_proportions",
    "srm_check",
]
