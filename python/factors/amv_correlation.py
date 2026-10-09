"""Trailing ETF / active-market-value return correlation on a market calendar."""
from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_amv_correlation(etf_close: pd.Series, amv_close: pd.Series,
                            window: int = 60) -> pd.Series:
    """Require window complete adjacent-session return pairs; never fill gaps.

    ``amv_close.index`` is the market calendar. The ETF caller must mask invalid
    sessions before calling. Future adjustment normalization cancels in ratios.
    """
    if window < 2:
        raise ValueError('window 必须至少为2')
    for series in (etf_close, amv_close):
        if series.index.has_duplicates or not series.index.is_monotonic_increasing:
            raise ValueError('日期必须唯一且递增')
        values = series.dropna().to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError('有效收盘价必须有限且为正')
    asset = etf_close.reindex(amv_close.index).pct_change(fill_method=None)
    market = amv_close.pct_change(fill_method=None)
    valid = asset.notna() & market.notna()
    asset, market = asset.where(valid), market.where(valid)
    result = asset.rolling(window, min_periods=window).corr(market)
    result = result.where((asset.rolling(window).std() > 0) & (market.rolling(window).std() > 0))
    return result.clip(-1., 1.).rename('factor')
