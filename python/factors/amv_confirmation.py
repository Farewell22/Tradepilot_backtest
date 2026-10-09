"""Causal MA20-cross entries with a five-session momentum confirmation window."""
from __future__ import annotations

from collections import deque

import pandas as pd


CONFIRMATION_SESSIONS = 5
MOMENTUM_THRESHOLD = .04


def generate_ma20_confirmations(amv: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "close"}
    if required.difference(amv.columns):
        raise ValueError("0AMV确认信号需要date和close")
    result = amv.loc[:, ["date", "close"]].copy()
    result["date"] = pd.to_datetime(result.date, errors="raise").dt.normalize()
    result["close"] = pd.to_numeric(result.close, errors="raise")
    result = result.sort_values("date").reset_index(drop=True)
    if result.date.duplicated().any() or result.close.isna().any() or (result.close <= 0).any():
        raise ValueError("0AMV数据存在重复日期、缺失价格或非正价格")
    result["ma20"] = result.close.rolling(20).mean()
    result["ma60"] = result.close.rolling(60).mean()
    result["momentum_3"] = result.close.pct_change(3)
    result["cross_ma20"] = (result.close > result.ma20) & (
        result.close.shift(1) <= result.ma20.shift(1)
    )
    # Compare price levels so division roundoff cannot turn exactly 4% into >4%.
    strong_momentum = result.close > result.close.shift(3) * (1 + MOMENTUM_THRESHOLD)
    result["ma20_confirmed"] = False
    result["ma20_cross_date"] = pd.NaT
    pending: deque[int] = deque()
    for index, row in enumerate(result.itertuples(index=False)):
        # The crossing day is session one; index+5 is already expired.
        while pending and index - pending[0] >= CONFIRMATION_SESSIONS:
            pending.popleft()
        if row.cross_ma20:
            pending.append(index)
        if pending and strong_momentum.iloc[index] and row.close > row.ma60:
            result.at[index, "ma20_confirmed"] = True
            result.at[index, "ma20_cross_date"] = result.at[pending[0], "date"]
            # Every active candidate gets its first confirmation on this date.
            pending.clear()
    return result
