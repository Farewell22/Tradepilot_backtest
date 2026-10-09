"""0AMV MA10/MA30 gap buy-point classification."""
from __future__ import annotations

from collections import deque

import pandas as pd


QUANTILE_LOOKBACK = 750
MIN_HISTORY = 250


def classify_buy_point(rank: float, previous_rank: float | None, ma3_rising: bool) -> str | None:
    """Classify a newly-entered gap rank; P90 and above is a veto."""
    if rank >= 0.90:
        return None
    prior = -1.0 if previous_rank is None or pd.isna(previous_rank) else float(previous_rank)
    if 0.30 <= rank < 0.35 and prior < 0.30 and ma3_rising:
        return "class_1"
    if 0.60 <= rank < 0.80 and prior < 0.60:
        return "class_2"
    if 0.40 <= rank < 0.60 and prior < 0.40:
        return "class_3"
    return None


def generate_buy_signals(amv: pd.DataFrame) -> pd.DataFrame:
    """Generate first-entry/upgrade signals using prior MA10>MA30 observations only."""
    result = amv.loc[:, ["date", "close"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result["close"] = pd.to_numeric(result["close"], errors="raise")
    result = result.sort_values("date").reset_index(drop=True)
    result["ma3"] = result["close"].rolling(3, min_periods=3).mean()
    result["ma10"] = result["close"].rolling(10, min_periods=10).mean()
    result["ma30"] = result["close"].rolling(30, min_periods=30).mean()
    result["gap10"] = result["close"] / result["ma10"] - 1.0
    result["ma3_rising"] = result["ma3"] > result["ma3"].shift(1)
    result["gap10_rank"] = pd.NA
    result["signal_type"] = pd.NA

    history: deque[float] = deque(maxlen=QUANTILE_LOOKBACK)
    previous_rank: float | None = None
    for index, row in result.iterrows():
        in_regime = bool(pd.notna(row["ma10"]) and row["ma10"] > row["ma30"])
        if not in_regime:
            previous_rank = None
            continue
        gap = float(row["gap10"])
        if len(history) >= MIN_HISTORY:
            values = list(history)
            rank = (sum(value < gap for value in values) + 0.5 * sum(value == gap for value in values)) / len(values)
            result.at[index, "gap10_rank"] = rank
            signal_type = classify_buy_point(rank, previous_rank, bool(row["ma3_rising"]))
            if signal_type == "class_1" or (signal_type is not None and gap > 0):
                result.at[index, "signal_type"] = signal_type
            previous_rank = rank
        else:
            previous_rank = None
        history.append(gap)
    return result.loc[result["signal_type"].notna(), ["date", "close", "ma10", "ma30", "gap10", "gap10_rank", "signal_type"]]
