"""Statistical evaluation for market-level factor observations."""
from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def evaluate_factor(observations: pd.DataFrame, factor_name: str, target_name: str, groups: int) -> dict[str, object]:
    sample = observations.loc[:, ["date", factor_name, target_name]].dropna().copy()
    base: dict[str, object] = {"factor": factor_name, "target": target_name, "sample_size": len(sample), "evaluable": False}
    if len(sample) < groups or sample[factor_name].nunique() < groups:
        return base | {"reason": "样本或因子取值不足"}
    try:
        sample["quantile"] = pd.qcut(sample[factor_name], groups, labels=False, duplicates="drop")
    except ValueError:
        return base | {"reason": "无法形成分位组"}
    if sample["quantile"].nunique() != groups:
        return base | {"reason": "分位组数量不足"}
    means = sample.groupby("quantile", observed=True)[target_name].mean()
    return base | {
        "evaluable": True,
        "pearson_correlation": sample[factor_name].corr(sample[target_name], method="pearson"),
        "spearman_correlation": sample[factor_name].rank().corr(sample[target_name].rank()),
        "q1_mean": means.iloc[0],
        "q5_mean": means.iloc[-1],
        "q5_minus_q1": means.iloc[-1] - means.iloc[0],
        "monotonic_direction": "increasing" if means.is_monotonic_increasing else "decreasing" if means.is_monotonic_decreasing else "mixed",
    }


def evaluate_all(observations: pd.DataFrame, factor_columns: Sequence[str], target_columns: Sequence[str], groups: int) -> pd.DataFrame:
    return pd.DataFrame([evaluate_factor(observations, factor, target, groups) for factor in factor_columns for target in target_columns])
