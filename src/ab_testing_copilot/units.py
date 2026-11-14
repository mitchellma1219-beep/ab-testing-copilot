"""Bring rows that are finer than the randomisation unit up to one row per unit.

Sessions, page views or orders of the same user are not independent observations. Analysing
them as if they were understates every standard error. Either aggregate to the unit with
:func:`aggregate_to_units` and analyse unit-level values, or keep a per-row metric as a ratio
of unit-level sums and analyse it with :func:`ab_testing_copilot.analysis.compare_ratios`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast, get_args

import pandas as pd

Aggregation = Literal["sum", "mean", "max", "min", "first", "unique"]
ROW_COUNT_COLUMN = "n_rows"
_NUMERIC_ONLY = {"sum", "mean"}


def parse_aggregations(text: str) -> dict[str, Aggregation]:
    """Parse ``col=how[,col=how...]`` (the CLI syntax) into an aggregation mapping."""
    out: dict[str, Aggregation] = {}
    for part in text.split(","):
        column, sep, how = part.partition("=")
        column, how = column.strip(), how.strip()
        if not sep or not column or how not in get_args(Aggregation):
            raise ValueError(
                f"bad aggregation '{part}': use column=how with how in "
                f"{list(get_args(Aggregation))}")
        if column in out:
            raise ValueError(f"column '{column}' is aggregated twice")
        out[column] = cast(Aggregation, how)
    return out


def aggregate_to_units(
    df: pd.DataFrame, unit_col: str, metrics: Mapping[str, Aggregation],
    variant_col: str = "variant",
) -> pd.DataFrame:
    """One row per (unit, variant) with each metric aggregated as declared.

    * ``sum`` / ``mean`` / ``max`` / ``min``: a unit whose rows contain a missing value gets a
      missing aggregate, so the loss stays visible to the missing-data diagnostic.
    * ``first``: the first non-missing value in row order.
    * ``unique``: the value must be constant within the unit (a segment, a pre-experiment
      covariate, the exposure date); otherwise a ``ValueError`` is raised.

    A column ``n_rows`` (rows per unit) is added; it is the natural denominator of a per-row
    ratio metric. A unit that appears under both variants yields two rows, which the analysis
    reports as contamination. Nothing is guessed: every column to keep must be listed.
    """
    if not metrics:
        raise ValueError("list at least one column to aggregate (column -> how)")
    needed = [unit_col, variant_col, *metrics]
    if len(set(needed)) != len(needed):
        raise ValueError("unit, variant and metric columns must all be different")
    missing = sorted(set(needed) - set(df.columns))
    if missing:
        raise ValueError(f"missing required column(s): {missing}; found {list(df.columns)}")
    if ROW_COUNT_COLUMN in needed:
        raise ValueError(f"'{ROW_COUNT_COLUMN}' is reserved for the row count per unit")
    for column, how in metrics.items():
        if how not in get_args(Aggregation):
            raise ValueError(f"unknown aggregation '{how}' for column '{column}'")
        numeric = pd.api.types.is_numeric_dtype(df[column]) and not pd.api.types.is_bool_dtype(
            df[column])
        if how in _NUMERIC_ONLY and not numeric:
            raise ValueError(
                f"column '{column}' must be numeric to aggregate with '{how}', "
                f"got dtype {df[column].dtype}")
    if len(df) == 0:
        raise ValueError("the table has no rows")
    for key in (unit_col, variant_col):
        n_missing = int(df[key].isna().sum())
        if n_missing:
            raise ValueError(
                f"{n_missing} row(s) have a missing '{key}'; drop or repair them explicitly "
                "before aggregating")

    keys = [unit_col, variant_col]
    grouped = df.groupby(keys, sort=True, observed=True)
    out = grouped.size().rename(ROW_COUNT_COLUMN).to_frame()
    for column, how in metrics.items():
        series = grouped[column]
        if how == "unique":
            distinct = series.nunique(dropna=True)
            bad = int((distinct > 1).sum())
            if bad:
                raise ValueError(
                    f"column '{column}' is not constant within {bad} unit(s); it cannot be "
                    "aggregated with 'unique'")
            out[column] = series.first()
        elif how == "first":
            out[column] = series.first()
        else:
            values = getattr(series, how)()
            has_missing = df[column].isna().groupby([df[unit_col], df[variant_col]],
                                                    sort=True, observed=True).any()
            out[column] = values.where(~has_missing)
    return out.reset_index()
