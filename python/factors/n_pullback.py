"""Causal three-cycle N pullback structure; no future confirmation is required for L3."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Pivot:
    kind: str
    index: int
    confirm_index: int
    price: float


def detect_pivots(daily: pd.DataFrame, threshold: float = .05) -> list[Pivot]:
    """Confirm alternating extrema with a close reversal, at most once per bar.

    After confirmation, the next candidate excludes the extremum's own bar:
    daily OHLC cannot tell which intraday extreme occurred first.
    """
    if not 0 < threshold < 1:
        raise ValueError("波段阈值必须在0和1之间")
    values = daily[["high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("价格必须是有限正数")
    if ((values[:, 0] < values[:, 1]) | (values[:, 2] > values[:, 0])
            | (values[:, 2] < values[:, 1])).any():
        raise ValueError("价格OHLC关系无效")
    if daily.date.duplicated().any() or not daily.date.is_monotonic_increasing:
        raise ValueError("日期必须唯一且递增")
    if not len(values):
        return []
    high, low, close = values.T
    seeking = "low"
    candidate: int | None = 0
    pivots = []
    for i in range(1, len(values)):
        if seeking == "low":
            if candidate is None or low[i] <= low[candidate]:
                candidate = i
            if close[i] >= low[candidate] * (1 + threshold):
                pivots.append(Pivot("low", candidate, i, float(low[candidate])))
                start = candidate + 1
                candidate = (start + len(high[start:i + 1]) - 1
                             - int(np.argmax(high[start:i + 1][::-1]))) if start <= i else None
                seeking = "high"
        else:
            if candidate is None or high[i] >= high[candidate]:
                candidate = i
            if close[i] <= high[candidate] * (1 - threshold):
                pivots.append(Pivot("high", candidate, i, float(high[candidate])))
                start = candidate + 1
                candidate = (start + len(low[start:i + 1]) - 1
                             - int(np.argmin(low[start:i + 1][::-1]))) if start <= i else None
                seeking = "low"
    return pivots


def evaluate_structure(daily: pd.DataFrame, asof: int, threshold: float = .05,
                       history: int = 252, *, pivots: list[Pivot] | None = None) -> dict:
    """Return raw weakest-low ratio, structure diagnostics and visible pivot dates."""
    if not 0 <= asof < len(daily) or history < 2:
        raise ValueError("观察位置或历史窗口无效")
    result = {"status": "insufficient_history", "factor": np.nan}
    if asof + 1 < history:
        return result
    if pivots is None:
        pivots = detect_pivots(daily.iloc[:asof + 1], threshold)
    visible = [p for p in pivots if p.confirm_index <= asof]
    high_positions = [i for i, p in enumerate(visible) if p.kind == "high"]
    if len(high_positions) < 3:
        return {**result, "status": "insufficient_structure"}
    sequence = visible[:high_positions[-1] + 1][-6:]
    if len(sequence) != 6 or [p.kind for p in sequence] != ["low", "high"] * 3:
        return {**result, "status": "insufficient_structure"}
    if sequence[0].index < asof - history + 1:
        return {**result, "status": "structure_outside_window"}
    for name, pivot in zip(("L0", "H1", "L1", "H2", "L2", "H3"), sequence):
        result.update({f"{name}_price": pivot.price, f"{name}_index": pivot.index,
                       f"{name}_date": str(pd.Timestamp(daily.date.iloc[pivot.index]).date()),
                       f"{name}_confirm_date": str(pd.Timestamp(daily.date.iloc[pivot.confirm_index]).date())})
    h1, h2, h3 = sequence[1::2]
    if not h1.price < h2.price < h3.price:
        return {**result, "status": "non_rising_highs"}
    if float(daily.close.iloc[asof]) > h3.price:
        return {**result, "status": "breakout"}
    start = h3.index + 1
    if start > asof:
        return {**result, "status": "no_pullback_bars"}
    lows = daily.low.iloc[start:asof + 1].to_numpy()
    last_index = start + len(lows) - 1 - int(np.argmin(lows[::-1]))
    l3 = float(daily.low.iloc[last_index])
    low_prices = [sequence[i].price for i in (0, 2, 4)] + [l3]
    low_indices = [sequence[i].index for i in (0, 2, 4)] + [last_index]
    if any(high.price <= low_prices[i] for i, high in enumerate((h1, h2, h3))):
        return {**result, "status": "non_positive_rise"}
    ratios = np.array(low_prices[1:]) / low_prices[:-1] - 1
    result.update(status="valid", factor=float(ratios.min()),
                  L3_price=l3, L3_index=last_index,
                  L3_date=str(pd.Timestamp(daily.date.iloc[last_index]).date()),
                  L3_confirm_date=None)
    for i, high in enumerate((h1, h2, h3), 1):
        result.update({f"low_change_{i}": float(ratios[i - 1]),
                       f"rise_{i}": high.price / low_prices[i - 1] - 1,
                       f"retrace_{i}": (high.price - low_prices[i]) / (high.price - low_prices[i - 1]),
                       f"pullback_bars_{i}": low_indices[i] - high.index})
    return result
