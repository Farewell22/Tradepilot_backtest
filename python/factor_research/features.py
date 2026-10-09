"""0AMV technical-factor definitions."""
from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def build_0amv_features(
    amv: pd.DataFrame,
    ma_windows: Sequence[int],
    return_windows: Sequence[int],
) -> pd.DataFrame:
    """Return chronologically ordered 0AMV features available at each close."""
    required = {"date", "close"}
    missing = required.difference(amv.columns)
    if missing:
        raise ValueError(f"0AMV 数据缺少列: {', '.join(sorted(missing))}")

    result = amv.loc[:, ["date", "close"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result["close"] = pd.to_numeric(result["close"], errors="raise")
    result = result.sort_values("date").reset_index(drop=True)

    for window in ma_windows:
        if window <= 0:
            raise ValueError("均线窗口必须为正整数")
        result[f"amv_ma_gap_{window}"] = (
            result["close"] / result["close"].rolling(window).mean() - 1.0
        )
    for window in return_windows:
        if window <= 0:
            raise ValueError("动量窗口必须为正整数")
        result[f"amv_return_{window}"] = result["close"].pct_change(window)

    return result
