"""Point-in-time forward-return and market-breadth labels."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


def _normalized_dates(frame: pd.DataFrame) -> pd.DataFrame:
    if "date" not in frame.columns:
        raise ValueError("数据缺少 date 列")
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    return result.sort_values("date").reset_index(drop=True)


def _validate_horizons(horizons: Sequence[int]) -> None:
    if not horizons or any(horizon <= 0 for horizon in horizons):
        raise ValueError("预测期必须包含正整数")


def build_forward_return_labels(
    prices: pd.DataFrame,
    horizons: Sequence[int],
    prefix: str,
) -> pd.DataFrame:
    """Label each date with close-to-close returns h later trading rows."""
    if "close" not in prices.columns:
        raise ValueError("价格数据缺少 close 列")
    _validate_horizons(horizons)
    result = _normalized_dates(prices.loc[:, ["date", "close"]])
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    labels = result.loc[:, ["date"]].copy()
    for horizon in horizons:
        future_close = result["close"].shift(-horizon)
        valid = (result["close"] > 0) & (future_close > 0)
        labels[f"{prefix}_forward_return_{horizon}"] = np.where(
            valid, future_close / result["close"] - 1.0, np.nan
        )
    return labels


def build_breadth_labels(
    closes: pd.DataFrame,
    horizons: Sequence[int],
) -> pd.DataFrame:
    """Count full-market future advancers, decliners, and unchanged stocks."""
    _validate_horizons(horizons)
    normalized = _normalized_dates(closes)
    codes = [column for column in normalized.columns if column != "date"]
    if not codes:
        raise ValueError("市场收盘价数据没有股票列")
    values = normalized.loc[:, codes].apply(pd.to_numeric, errors="coerce")
    labels = normalized.loc[:, ["date"]].copy()

    for horizon in horizons:
        future = values.shift(-horizon)
        valid = (values > 0) & (future > 0)
        returns = future / values - 1.0
        labels[f"eligible_count_{horizon}"] = valid.sum(axis=1).astype(float)
        labels[f"advancers_{horizon}"] = ((returns > 0) & valid).sum(axis=1).astype(float)
        labels[f"decliners_{horizon}"] = ((returns < 0) & valid).sum(axis=1).astype(float)
        labels[f"unchanged_{horizon}"] = ((returns == 0) & valid).sum(axis=1).astype(float)
        labels[f"advance_ratio_{horizon}"] = (
            labels[f"advancers_{horizon}"] / labels[f"eligible_count_{horizon}"]
        )
        labels.loc[labels.index[-horizon:], [
            f"eligible_count_{horizon}",
            f"advancers_{horizon}",
            f"decliners_{horizon}",
            f"unchanged_{horizon}",
            f"advance_ratio_{horizon}",
        ]] = np.nan
    return labels
