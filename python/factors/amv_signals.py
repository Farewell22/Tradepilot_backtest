"""Reusable 0AMV labels for strategy and dashboard consumers."""
from __future__ import annotations

import pandas as pd


def align_amv_sell_signals(etf_frame: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    """Append date-aligned AMV buy/sell labels to every ETF row."""
    date_column = "date" if "date" in etf_frame.columns else "时间" if "时间" in etf_frame.columns else None
    if date_column is None:
        raise ValueError("ETF 数据必须包含 date 或 时间 列")
    required = {"date", "sell_types", "sell_warning_types"}
    if not required.issubset(signals.columns):
        raise ValueError("0AMV 信号数据必须包含 date、sell_types 和 sell_warning_types 列")

    result = etf_frame.copy()
    dates = pd.to_datetime(result[date_column], errors="raise").dt.normalize()
    columns = ["date", "sell_types", "sell_warning_types"]
    if "sell_momentum_warning_types" in signals.columns:
        columns.append("sell_momentum_warning_types")
    if "signal_type" in signals.columns:
        columns.append("signal_type")
    signal_frame = signals.loc[:, columns].copy()
    signal_frame["date"] = pd.to_datetime(signal_frame["date"], errors="raise").dt.normalize()
    if signal_frame["date"].duplicated().any():
        raise ValueError("0AMV 卖点数据存在重复日期")
    signal_map = signal_frame.set_index("date")

    def encode(value: object) -> str:
        if value is None or (not isinstance(value, (list, tuple)) and pd.isna(value)):
            return ""
        if not isinstance(value, (list, tuple)):
            return str(value)
        return "|".join(str(item) for item in value)

    result["amv_sell_types"] = [encode(signal_map.at[date, "sell_types"]) if date in signal_map.index else "" for date in dates]
    result["amv_sell_warning_types"] = [encode(signal_map.at[date, "sell_warning_types"]) if date in signal_map.index else "" for date in dates]
    result["amv_sell_momentum_warning_types"] = [
        encode(signal_map.at[date, "sell_momentum_warning_types"])
        if date in signal_map.index and "sell_momentum_warning_types" in signal_map.columns
        else "" for date in dates
    ]
    result["amv_buy_types"] = [
        encode(signal_map.at[date, "signal_type"])
        if date in signal_map.index and "signal_type" in signal_map.columns
        and signal_map.at[date, "signal_type"] in {"best", "secondary"}
        else "" for date in dates
    ]
    return result
