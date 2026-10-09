"""Shared market-data normalization for stock and ETF backtests."""
from __future__ import annotations

import pandas as pd


_ALIASES = {
    "日期": "date", "时间": "date", "开盘": "open", "开盘价": "open",
    "最高": "high", "最高价": "high", "最低": "low", "最低价": "low",
    "收盘": "close", "收盘价": "close", "成交量": "volume",
}


def normalize_etf_intraday(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize source columns while preserving each intraday timestamp."""
    result = frame.rename(columns=_ALIASES).copy()
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required.difference(result.columns)
    if missing:
        raise ValueError(f"ETF 数据缺少列: {', '.join(sorted(missing))}")
    result = result.loc[:, ["date", "open", "high", "low", "close", "volume"]]
    result["date"] = pd.to_datetime(result["date"], errors="raise")
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="raise")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("ETF OHLC 必须为正")
    return result.sort_values("date").reset_index(drop=True)


def normalize_etf_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate canonical or source-specific ETF OHLCV rows to sessions."""
    result = normalize_etf_intraday(frame)
    result["date"] = result["date"].dt.normalize()
    if result["date"].duplicated().any():
        result = result.groupby("date", as_index=False, sort=True).agg(
            open=("open", "first"), high=("high", "max"), low=("low", "min"),
            close=("close", "last"), volume=("volume", "sum"),
        )
    return result.sort_values("date").reset_index(drop=True)
