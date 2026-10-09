"""Trailing style strength and close-to-close total returns (no future factors)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _positive_series(values: pd.Series) -> None:
    if values.empty or not np.isfinite(values.to_numpy(dtype=float)).all() or (values <= 0).any():
        raise ValueError("价格必须非空、有限且为正")
    if values.index.has_duplicates or not values.index.is_monotonic_increasing:
        raise ValueError("日期必须唯一且递增")


def total_return_index(prices: pd.DataFrame, actions: pd.DataFrame) -> pd.Series:
    """Normalize wealth to 100; reinvest ex-date cash at that day's close.

    share_ratio is new units per old unit; cash_per_share is cash per pre-event
    unit. price_effective_date describes the raw quote boundary, which can
    follow the legal split date when that date was a suspension.
    """
    frame = prices.loc[:, ["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    close = frame.sort_values("date").set_index("date")["close"].astype(float)
    _positive_series(close)
    ratios = pd.Series(1., index=close.index)
    cash = pd.Series(0., index=close.index)
    if not actions.empty:
        events = actions.loc[:, ["price_effective_date", "share_ratio", "cash_per_share"]].copy()
        events["price_effective_date"] = pd.to_datetime(events["price_effective_date"], errors="raise").dt.normalize()
        if events.price_effective_date.isna().any() or events.price_effective_date.duplicated().any():
            raise ValueError("公司行动日期必须有效且唯一")
        for row in events.itertuples(index=False):
            ratio, dividend = float(row.share_ratio), float(row.cash_per_share)
            if not np.isfinite([ratio, dividend]).all() or ratio <= 0 or dividend < 0:
                raise ValueError("公司行动的份额比例和派息必须有效")
            if close.index[0] < row.price_effective_date <= close.index[-1]:
                if row.price_effective_date not in close.index:
                    raise ValueError(f"公司行动日期缺少报价: {row.price_effective_date}")
                ratios.at[row.price_effective_date] = ratio
                cash.at[row.price_effective_date] = dividend
    gross = (ratios * close + cash) / close.shift(1)
    gross.iloc[0] = 1.
    return (100 * gross.cumprod()).rename("total_return_index")


def relative_strength(small: pd.Series, large: pd.Series, lookback: int = 20) -> pd.Series:
    """Difference of simple trailing returns on one shared session calendar."""
    if not small.index.equals(large.index):
        raise ValueError("两只ETF的日期必须完全一致")
    if not isinstance(lookback, int) or lookback <= 0:
        raise ValueError("回看交易日数必须为正整数")
    _positive_series(small)
    _positive_series(large)
    return (small / small.shift(lookback) - large / large.shift(lookback)).rename("relative_strength")


def rolling_percentile(values: pd.Series, window: int = 100) -> pd.Series:
    """Inclusive trailing empirical percentile; midpoint ties, full warmup."""
    if not isinstance(window, int) or window <= 0:
        raise ValueError("百分位窗口必须为正整数")
    if np.isinf(values.to_numpy(dtype=float)).any():
        raise ValueError("因子不能含无穷值")

    def midpoint(sample: np.ndarray) -> float:
        return 100 * ((sample < sample[-1]).sum() + .5 * (sample == sample[-1]).sum()) / window

    return values.rolling(window, min_periods=window).apply(midpoint, raw=True).rename("percentile")


def forward_return(values: pd.Series, horizon: int) -> pd.Series:
    """Future labels only; last H observations remain missing independently."""
    if not isinstance(horizon, int) or horizon <= 0:
        raise ValueError("远期交易日数必须为正整数")
    _positive_series(values)
    return (values.shift(-horizon) / values - 1).rename(f"forward_return_{horizon}")
