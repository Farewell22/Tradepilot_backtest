"""0AMV buy-point classification and forward-return statistics."""
from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


SIGNAL_TYPES = ("best", "secondary", "worst")
SIGNAL_NAMES = {"best": "最佳买点", "secondary": "次级买点", "worst": "最差买点"}
SELL_QUANTILE_WINDOW = 750
SELL_QUANTILE = 0.85
SELL_WARNING_QUANTILE = 0.90
MOMENTUM_WARNING_QUANTILE = 0.20
MOMENTUM_WARNING_MIN_CANDIDATES = 30


def _normalize_date(value: str | None) -> pd.Timestamp | None:
    if value is None:
        return None
    return pd.to_datetime(value, format="%Y%m%d", errors="raise").normalize()


def low_momentum_warning(
    momentum_3: pd.Series,
    high_gap_candidate: pd.Series,
    window: int = SELL_QUANTILE_WINDOW,
    min_periods: int = MOMENTUM_WARNING_MIN_CANDIDATES,
) -> pd.Series:
    """Return candidate days whose 3-day momentum is in prior candidate P20."""
    if not 0 < min_periods <= window:
        raise ValueError("低动量预警的 min_periods 必须在 1 到 window 之间")
    candidate_momentum = momentum_3.where(high_gap_candidate)
    prior_p20 = candidate_momentum.rolling(window, min_periods=min_periods).quantile(
        MOMENTUM_WARNING_QUANTILE
    ).shift(1)
    return high_gap_candidate & (momentum_3 <= prior_p20)


def analyze_amv_buy_points(
    amv: pd.DataFrame,
    horizons: Sequence[int] = (1, 3, 5, 10),
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return all AMV bars and mutually-exclusive buy-point statistics."""
    required = {"date", "open", "high", "low", "close"}
    missing = required.difference(amv.columns)
    if missing:
        raise ValueError(f"0AMV 数据缺少列: {', '.join(sorted(missing))}")
    if not horizons or any(int(horizon) <= 0 for horizon in horizons):
        raise ValueError("预测期必须包含正整数")

    result = amv.loc[:, ["date", "open", "high", "low", "close"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    if result["date"].duplicated().any():
        raise ValueError("0AMV 数据存在重复日期")
    for column in ("open", "high", "low", "close"):
        result[column] = pd.to_numeric(result[column], errors="raise")
    if (result["close"] <= 0).any():
        raise ValueError("0AMV 收盘价必须为正")
    result = result.sort_values("date").reset_index(drop=True)

    result["ma10"] = result["close"].rolling(10).mean()
    result["ma20"] = result["close"].rolling(20).mean()
    result["ma30"] = result["close"].rolling(30).mean()
    result["ma3"] = result["close"].rolling(3).mean()
    result["momentum_3"] = result["close"].pct_change(3)
    gap10 = result["close"] / result["ma10"] - 1.0
    gap20 = result["close"] / result["ma20"] - 1.0
    gap10_p85 = gap10.rolling(SELL_QUANTILE_WINDOW, min_periods=SELL_QUANTILE_WINDOW).quantile(SELL_QUANTILE).shift(1)
    gap20_p85 = gap20.rolling(SELL_QUANTILE_WINDOW, min_periods=SELL_QUANTILE_WINDOW).quantile(SELL_QUANTILE).shift(1)
    gap10_p90 = gap10.rolling(SELL_QUANTILE_WINDOW, min_periods=SELL_QUANTILE_WINDOW).quantile(SELL_WARNING_QUANTILE).shift(1)
    gap20_p90 = gap20.rolling(SELL_QUANTILE_WINDOW, min_periods=SELL_QUANTILE_WINDOW).quantile(SELL_WARNING_QUANTILE).shift(1)
    prior_close = result["close"].shift(1)
    prior_ma10 = result["ma10"].shift(1)
    prior_ma20 = result["ma20"].shift(1)
    cross_ma10 = (result["close"] > result["ma10"]) & (prior_close <= prior_ma10)
    cross_ma20 = (result["close"] > result["ma20"]) & (prior_close <= prior_ma20)

    best = cross_ma20 & (result["momentum_3"] > 0.04)
    secondary = (
        (result["close"] > result["ma20"])
        & cross_ma10
        & (result["momentum_3"] > 0.03)
    )
    worst = (result["close"] > result["ma20"]) & (result["momentum_3"] > 0.04)
    ma3_not_rising = result["ma3"] <= result["ma3"].shift(1)
    ma10_above_ma30 = result["ma10"] > result["ma30"]
    sell_1 = (gap10 > gap10_p85) & ma3_not_rising
    sell_2 = (gap20 > gap20_p85) & ma3_not_rising
    sell_1_warning = (gap10 > gap10_p90) & ma3_not_rising
    sell_2_warning = (gap20 > gap20_p90) & ma3_not_rising
    early_sell_1_candidate = ma10_above_ma30 & (gap10 > gap10_p85)
    early_sell_2_candidate = ma10_above_ma30 & (gap20 > gap20_p85)
    early_sell_1_warning = low_momentum_warning(result["momentum_3"], early_sell_1_candidate)
    early_sell_2_warning = low_momentum_warning(result["momentum_3"], early_sell_2_candidate)
    result["sell_types"] = [
        [signal_type for matched, signal_type in ((sell_1.iloc[index], "sell_1"), (sell_2.iloc[index], "sell_2")) if matched]
        for index in range(len(result))
    ]
    result["sell_warning_types"] = [
        [signal_type for matched, signal_type in ((sell_1_warning.iloc[index], "sell_1"), (sell_2_warning.iloc[index], "sell_2")) if matched]
        for index in range(len(result))
    ]
    result["sell_momentum_warning_types"] = [
        [
            signal_type
            for matched, signal_type in (
                (early_sell_1_warning.iloc[index], "sell_1"),
                (early_sell_2_warning.iloc[index], "sell_2"),
            )
            if matched
        ]
        for index in range(len(result))
    ]
    result["signal_type"] = pd.Series(pd.NA, index=result.index, dtype="string")
    result.loc[best, "signal_type"] = "best"
    result.loc[~best & secondary, "signal_type"] = "secondary"
    result.loc[~best & ~secondary & worst, "signal_type"] = "worst"

    for horizon in horizons:
        horizon = int(horizon)
        result[f"forward_return_{horizon}_pct"] = (
            result["close"].shift(-horizon) / result["close"] - 1.0
        ) * 100

    filtered = result
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    if start is not None:
        filtered = filtered.loc[filtered["date"] >= start]
    if end is not None:
        filtered = filtered.loc[filtered["date"] <= end]
    filtered = filtered.reset_index(drop=True)

    signal_rows = filtered.loc[filtered["signal_type"].notna()]
    summaries = []
    for signal_type in SIGNAL_TYPES:
        rows = signal_rows.loc[signal_rows["signal_type"] == signal_type]
        item = {
            "signal_type": signal_type,
            "signal_name": SIGNAL_NAMES[signal_type],
            "count": int(len(rows)),
        }
        for horizon in horizons:
            horizon = int(horizon)
            values = rows[f"forward_return_{horizon}_pct"].dropna()
            item[f"avg_forward_return_{horizon}_pct"] = float(values.mean()) if not values.empty else None
            item[f"win_rate_{horizon}_pct"] = float((values > 0).mean() * 100) if not values.empty else None
        summaries.append(item)
    return filtered, pd.DataFrame(summaries)
