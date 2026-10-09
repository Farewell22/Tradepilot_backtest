"""Point-in-time B1 event-study primitives."""
from __future__ import annotations

import numpy as np
import pandas as pd

from python.factors.b1_filter import filter_b1_candidates
from python.factors.z_indicators import compute_all_indicators


def aggregate_bars_to_signal_time(bars: pd.DataFrame, signal_time: str = "14:45:00") -> pd.DataFrame:
    """Aggregate intraday bars through signal_time into a provisional daily bar."""
    required = {"code", "date", "trade_time", "open", "close", "high", "low", "vol", "amount", "pre_close"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"分钟数据缺少列: {', '.join(sorted(missing))}")
    frame = bars.copy()
    frame["trade_time"] = pd.to_datetime(frame["trade_time"], errors="raise")
    eligible = frame.loc[frame["trade_time"].dt.strftime("%H:%M:%S") <= signal_time].sort_values(["code", "trade_time"])
    if eligible.empty:
        return pd.DataFrame(columns=["code", "date", "open", "close", "high", "low", "vol", "amount", "pre_close"])
    grouped = eligible.groupby(["code", "date"], as_index=False, sort=False)
    return grouped.agg(
        open=("open", "first"), close=("close", "last"), high=("high", "max"), low=("low", "min"),
        vol=("vol", "sum"), amount=("amount", "sum"), pre_close=("pre_close", "first"),
    )


def attach_forward_event_returns(
    events: pd.DataFrame, close_panel: pd.DataFrame, horizons: list[int]
) -> pd.DataFrame:
    """Attach close-to-entry returns at future trading-date offsets."""
    required = {"signal_date", "code", "entry_price"}
    missing = required.difference(events.columns)
    if missing:
        raise ValueError(f"事件数据缺少列: {', '.join(sorted(missing))}")
    panel = close_panel.copy()
    panel["date"] = pd.to_datetime(panel["date"], errors="raise").dt.normalize()
    panel = panel.sort_values("date").reset_index(drop=True)
    positions = {date: position for position, date in enumerate(panel["date"])}
    result = events.copy()
    result["signal_date"] = pd.to_datetime(result["signal_date"], errors="raise").dt.normalize()
    for horizon in horizons:
        exit_prices: list[float] = []
        for event in result.itertuples(index=False):
            position = positions.get(event.signal_date)
            exit_position = None if position is None else position + horizon
            if exit_position is None or exit_position >= len(panel) or event.code not in panel.columns:
                exit_prices.append(float("nan"))
            else:
                exit_prices.append(panel.iloc[exit_position][event.code])
        result[f"exit_close_{horizon}"] = exit_prices
        result[f"forward_return_{horizon}"] = result[f"exit_close_{horizon}"] / result["entry_price"] - 1.0
    return result


def attach_lagged_amv_features(events: pd.DataFrame, amv_features: pd.DataFrame) -> pd.DataFrame:
    """Attach T-1 final 0AMV features to each T-day signal event."""
    if "signal_date" not in events.columns or "date" not in amv_features.columns:
        raise ValueError("事件数据须含 signal_date，0AMV 特征须含 date")
    lagged = amv_features.copy().sort_values("date").reset_index(drop=True)
    lagged["date"] = pd.to_datetime(lagged["date"], errors="raise").dt.normalize()
    lagged["signal_date"] = lagged["date"].shift(-1)
    result = events.copy()
    result["signal_date"] = pd.to_datetime(result["signal_date"], errors="raise").dt.normalize()
    return result.merge(lagged.drop(columns="date"), on="signal_date", how="left")


def compute_provisional_indicators(final_daily: pd.DataFrame, provisional_daily: pd.DataFrame) -> pd.DataFrame:
    """Compute same-day indicators from prior final bars and a 14:45 provisional bar.

    ``final_daily`` may include the day's 15:00 bar, but all state columns are
    shifted by one stock observation before they are combined with the
    provisional bar.  Therefore the output is point-in-time at 14:45.
    """
    required = {"code", "date", "close", "high", "low"}
    missing = required.difference(final_daily.columns) | required.difference(provisional_daily.columns)
    if missing:
        raise ValueError(f"日线数据缺少列: {', '.join(sorted(missing))}")
    frame = final_daily.copy().sort_values(["code", "date"]).reset_index(drop=True)
    state_columns = ["_prev_k", "_prev_d", "_prior_high8", "_prior_low8", "_prev_ema1", "_prev_ema2"]
    for window in (14, 28, 57, 114):
        state_columns.append(f"_prior_close_sum_{window}")
    state = np.full((len(frame), len(state_columns)), np.nan, dtype=float)
    alpha = 2.0 / 11.0
    for _, indexes in frame.groupby("code", sort=False).indices.items():
        positions = np.asarray(indexes)
        sub = frame.iloc[positions]
        close = sub["close"].to_numpy(dtype=float)
        high = sub["high"].to_numpy(dtype=float)
        low = sub["low"].to_numpy(dtype=float)
        count = len(sub)
        high_n = pd.Series(high).rolling(9, min_periods=9).max().to_numpy()
        low_n = pd.Series(low).rolling(9, min_periods=9).min().to_numpy()
        k = np.full(count, 50.0)
        d = np.full(count, 50.0)
        for index in range(8, count):
            rsv = (close[index] - low_n[index]) / (high_n[index] - low_n[index] + 1e-9) * 100.0
            k[index] = 2.0 / 3.0 * k[index - 1] + 1.0 / 3.0 * rsv
            d[index] = 2.0 / 3.0 * d[index - 1] + 1.0 / 3.0 * k[index]
        ema1 = pd.Series(close).ewm(span=10, adjust=False).mean().to_numpy()
        ema2 = pd.Series(ema1).ewm(span=10, adjust=False).mean().to_numpy()
        values = [
            pd.Series(k).shift(1).to_numpy(),
            pd.Series(d).shift(1).to_numpy(),
            pd.Series(high).rolling(8, min_periods=8).max().shift(1).to_numpy(),
            pd.Series(low).rolling(8, min_periods=8).min().shift(1).to_numpy(),
            pd.Series(ema1).shift(1).to_numpy(),
            pd.Series(ema2).shift(1).to_numpy(),
        ]
        values.extend(
            pd.Series(close).rolling(window - 1, min_periods=window - 1).sum().shift(1).to_numpy()
            for window in (14, 28, 57, 114)
        )
        state[positions] = np.column_stack(values)
    state_frame = pd.DataFrame(state, columns=state_columns)
    state_frame[["code", "date"]] = frame[["code", "date"]]
    result = provisional_daily.merge(state_frame, on=["code", "date"], how="left")
    prior_high = result["_prior_high8"].to_numpy()
    prior_low = result["_prior_low8"].to_numpy()
    high = result["high"].to_numpy(dtype=float)
    low = result["low"].to_numpy(dtype=float)
    close = result["close"].to_numpy(dtype=float)
    rsv = (close - np.minimum(prior_low, low)) / (np.maximum(prior_high, high) - np.minimum(prior_low, low) + 1e-9) * 100.0
    valid_kdj = np.isfinite(prior_high) & np.isfinite(prior_low)
    k = np.where(valid_kdj, 2.0 / 3.0 * result["_prev_k"] + 1.0 / 3.0 * rsv, 50.0)
    d = np.where(valid_kdj, 2.0 / 3.0 * result["_prev_d"] + 1.0 / 3.0 * k, 50.0)
    result["J"] = 3.0 * k - 2.0 * d
    ema1 = alpha * close + (1.0 - alpha) * result["_prev_ema1"]
    result["zxdq"] = alpha * ema1 + (1.0 - alpha) * result["_prev_ema2"]
    means = [
        (result[f"_prior_close_sum_{window}"] + close) / window
        for window in (14, 28, 57, 114)
    ]
    result["zxdkx"] = sum(means) / 4.0
    return result.drop(columns=state_columns)


def score_prefiltered_day(
    historical_daily: pd.DataFrame,
    provisional_daily: pd.DataFrame,
    eligible_codes: set[str],
    weights: dict,
    config: dict,
) -> pd.DataFrame:
    """Score only codes that already passed the point-in-time KDJ/ZX filter."""
    if not eligible_codes:
        return pd.DataFrame(columns=["signal_date", "code", "verdict", "total", "signal_type", "entry_price"])
    signal_date = provisional_daily["date"].iloc[0]
    combined = pd.concat(
        [historical_daily.loc[historical_daily["code"].isin(eligible_codes)], provisional_daily.loc[provisional_daily["code"].isin(eligible_codes)]],
        ignore_index=True,
    ).sort_values(["code", "date"])
    eligible = {code: data.tail(140).copy() for code, data in combined.groupby("code", sort=False)}
    ratings = filter_b1_candidates(eligible, weights, config, accepted_verdicts=("PASS", "WATCH"))
    return pd.DataFrame([
        {"signal_date": signal_date, "code": rating.code, "verdict": rating.verdict, "total": rating.total, "signal_type": rating.signal_type, "entry_price": rating.close}
        for rating in ratings
    ])


def score_signal_day(
    historical_daily: pd.DataFrame, provisional_daily: pd.DataFrame, weights: dict, config: dict, j_threshold: float = 13.0
) -> pd.DataFrame:
    """Recompute B1 PASS/WATCH signals with a 14:45 provisional daily bar."""
    signal_date = provisional_daily["date"].iloc[0]
    combined = pd.concat([historical_daily, provisional_daily], ignore_index=True).sort_values(["code", "date"])
    eligible: dict[str, pd.DataFrame] = {}
    for code, history in combined.groupby("code", sort=False):
        indicators = compute_all_indicators(history.reset_index(drop=True))
        current = indicators.iloc[-1]
        if (
            current["J"] < j_threshold
            and current["close"] > current["zxdkx"]
            and current["zxdq"] > current["zxdkx"]
        ):
            eligible[code] = indicators.tail(140).copy()
    ratings = filter_b1_candidates(eligible, weights, config, accepted_verdicts=("PASS", "WATCH"))
    return pd.DataFrame([
        {"signal_date": signal_date, "code": rating.code, "verdict": rating.verdict, "total": rating.total, "signal_type": rating.signal_type, "entry_price": rating.close}
        for rating in ratings
    ])
