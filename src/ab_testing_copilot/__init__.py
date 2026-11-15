"""A/B Testing Copilot: design, diagnose, analyze, simulate and decide on experiments."""

from ab_testing_copilot.aa import aa_check
from ab_testing_copilot.analysis import (
    adjust_pvalues,
    bootstrap_mean_diff,
    compare_means,
    compare_proportions,
    compare_ratios,
    cuped_adjust,
)
from ab_testing_copilot.decision import decide
from ab_testing_copilot.design import (
    duration_days,
    mde_for_means,
    mde_for_proportions,
    power_curve,
    power_for_means,
    power_for_proportions,
    sample_size_for_means,
    sample_size_for_proportions,
)
from ab_testing_copilot.diagnostics import srm_check
from ab_testing_copilot.experiment import (
    ExperimentConfig,
    GuardrailSpec,
    MetricSpec,
    analyze_experiment,
)
from ab_testing_copilot.plan import PlanRequest, build_plan
from ab_testing_copilot.sequential import (
    SequentialDesign,
    alpha_spent,
    inflation_factor,
    sequential_boundaries,
    sequential_look,
    sequential_power,
)
from ab_testing_copilot.units import aggregate_to_units

__version__ = "0.1.0"

__all__ = [
    "ExperimentConfig",
    "GuardrailSpec",
    "MetricSpec",
    "PlanRequest",
    "SequentialDesign",
    "aa_check",
    "adjust_pvalues",
    "aggregate_to_units",
    "alpha_spent",
    "analyze_experiment",
    "bootstrap_mean_diff",
    "build_plan",
    "compare_means",
    "compare_proportions",
    "compare_ratios",
    "cuped_adjust",
    "decide",
    "duration_days",
    "inflation_factor",
    "mde_for_means",
    "mde_for_proportions",
    "power_curve",
    "power_for_means",
    "power_for_proportions",
    "sample_size_for_means",
    "sample_size_for_proportions",
    "sequential_boundaries",
    "sequential_look",
    "sequential_power",
    "srm_check",
]
