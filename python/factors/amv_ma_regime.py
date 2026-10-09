"""Causal daily 0AMV simple-moving-average regimes."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_amv_ma_regimes(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.loc[:, ["date", "close"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result["close"] = pd.to_numeric(result["close"], errors="raise")
    result = result.sort_values("date").reset_index(drop=True)
    if result.date.duplicated().any() or not np.isfinite(result.close).all() or (result.close <= 0).any():
        raise ValueError("0AMV requires unique dates and finite positive closes")
    for period in (30, 60):
        result[f"ma{period}"] = result.close.rolling(period, min_periods=period).mean()
        result[f"below_ma{period}"] = result.close < result[f"ma{period}"]
    return result
