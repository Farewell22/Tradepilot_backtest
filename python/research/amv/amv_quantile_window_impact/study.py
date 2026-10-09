"""Measure 0AMV gap-rank window length effects on signals, correlations, and ETF backtests."""
from __future__ import annotations

from python.research.date_scope import scoped_ranges

import argparse
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

from python.factors.amv_buy_points import low_momentum_warning
from python.strategies.etf_amv.strategy import normalize_etf_history, normalize_etf_intraday
from python.research.amv.ma10_above_ma30_gap.study import (
    INITIAL_CASH,
    SAMPLES,
    _metrics,
    _next_session_schedule,
    generate_trend_exit_signals,
    run_full_position_backtest,
)
from python.factor_research.data import load_amv_csv


WINDOWS = (100, 200, 300, 400, 500, 750)


def minimum_history(window: int) -> int:
    """Keep the production 750/250 warm-up ratio for every comparison window."""
    return int(np.ceil(int(window) / 3.0))


def rolling_gap_rank(values: pd.Series, window: int, min_history: int) -> pd.Series:
    """Rank each observation against prior values only; NaN values do not enter history."""
    history: deque[float] = deque(maxlen=int(window))
    output: list[float] = []
    for value in values:
        if pd.isna(value):
            output.append(np.nan)
            continue
        current = float(value)
        if len(history) < int(min_history):
            output.append(np.nan)
        else:
            prior = list(history)
            output.append((sum(item < current for item in prior) + 0.5 * sum(item == current for item in prior)) / len(prior))
        history.append(current)
    return pd.Series(output, index=values.index, dtype=float)


def spearman_correlation(left: pd.Series, right: pd.Series) -> float:
    """Spearman rank correlation without pandas' optional SciPy dependency."""
    paired = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(paired) < 2:
        return float("nan")
    return float(paired["left"].rank().corr(paired["right"].rank()))


def stage_correlations(states: pd.DataFrame, start: str, end: str) -> dict[int, float]:
    """Return stage-local rank/forward-return correlations, avoiding cross-period leakage."""
    stage = states.loc[states["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
    return {
        horizon: spearman_correlation(stage["gap10_rank"], stage[f"forward_return_{horizon}_pct"])
        for horizon in (5, 10)
    }


def _states(amv: pd.DataFrame, window: int) -> pd.DataFrame:
    states = amv.loc[:, ["date", "close"]].copy().sort_values("date").reset_index(drop=True)
    states["date"] = pd.to_datetime(states["date"], errors="raise").dt.normalize()
    states["close"] = pd.to_numeric(states["close"], errors="raise")
    states["ma3"] = states["close"].rolling(3, min_periods=3).mean()
    states["ma10"] = states["close"].rolling(10, min_periods=10).mean()
    states["ma20"] = states["close"].rolling(20, min_periods=20).mean()
    states["ma30"] = states["close"].rolling(30, min_periods=30).mean()
    states["momentum_3"] = states["close"].pct_change(3)
    states["gap10"] = states["close"] / states["ma10"] - 1.0
    states["gap20"] = states["close"] / states["ma20"] - 1.0
    in_regime = states["ma10"] > states["ma30"]
    states["gap10_rank"] = rolling_gap_rank(states["gap10"].where(in_regime), window, minimum_history(window))
    for horizon in (5, 10):
        states[f"forward_return_{horizon}_pct"] = (states["close"].shift(-horizon) / states["close"] - 1.0) * 100.0
    return states


def parameterized_buy_signals(amv: pd.DataFrame, window: int) -> pd.DataFrame:
    """Generate the current class-2/class-3 entries with a configurable prior-history rank window."""
    states = _states(amv, window)
    previous_rank: float | None = None
    signal_type: list[str | None] = []
    for row in states.itertuples():
        if not bool(pd.notna(row.ma10) and row.ma10 > row.ma30):
            previous_rank = None
            signal_type.append(None)
            continue
        rank = row.gap10_rank
        value: str | None = None
        if pd.notna(rank):
            prior = -1.0 if previous_rank is None else previous_rank
            if 0.60 <= rank < 0.80 and prior < 0.60 and row.gap10 > 0:
                value = "class_2"
            elif 0.40 <= rank < 0.60 and prior < 0.40 and row.gap10 > 0:
                value = "class_3"
            previous_rank = float(rank)
        else:
            previous_rank = None
        signal_type.append(value)
    states["signal_type"] = signal_type
    return states.loc[states["signal_type"].notna(), ["date", "gap10_rank", "signal_type"]].reset_index(drop=True)


def parameterized_low_momentum_sells(amv: pd.DataFrame, window: int) -> pd.DataFrame:
    """Generate the same P85 + candidate-momentum-P20 sell warnings at a configurable window."""
    states = _states(amv, window)
    gap10_p85 = states["gap10"].rolling(window, min_periods=window).quantile(0.85).shift(1)
    gap20_p85 = states["gap20"].rolling(window, min_periods=window).quantile(0.85).shift(1)
    in_regime = states["ma10"] > states["ma30"]
    sell_1 = low_momentum_warning(states["momentum_3"], in_regime & (states["gap10"] > gap10_p85), window=window, min_periods=30)
    sell_2 = low_momentum_warning(states["momentum_3"], in_regime & (states["gap20"] > gap20_p85), window=window, min_periods=30)
    states["sell_momentum_warning_types"] = [
        [kind for active, kind in ((sell_1.iloc[index], "sell_1"), (sell_2.iloc[index], "sell_2")) if active]
        for index in states.index
    ]
    return states.loc[states["sell_momentum_warning_types"].map(bool), ["date", "sell_momentum_warning_types"]].reset_index(drop=True)


def run_research(amv_path: Path, etf_path: Path, output_dir: Path) -> pd.DataFrame:
    amv = load_amv_csv(amv_path)
    raw_etf = pd.read_csv(etf_path)
    daily_etf = normalize_etf_history(raw_etf)
    intraday_etf = normalize_etf_intraday(raw_etf)
    trend_exits = generate_trend_exit_signals(amv)
    trend_schedule = _next_session_schedule(trend_exits, daily_etf["date"], "exit_type")
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for window in WINDOWS:
        states = _states(amv, window)
        buys = parameterized_buy_signals(amv, window)
        sells = parameterized_low_momentum_sells(amv, window)
        buys.to_csv(output_dir / f"buy_signals_window_{window}.csv", index=False, encoding="utf-8-sig")
        sells.to_csv(output_dir / f"sell_signals_window_{window}.csv", index=False, encoding="utf-8-sig")
        buy_schedule = _next_session_schedule(buys, daily_etf["date"], "signal_type")
        sell_schedule = _next_session_schedule(sells, daily_etf["date"], "sell_momentum_warning_types")
        for stage, (start, end) in scoped_ranges(SAMPLES).items():
            correlations = stage_correlations(states, start, end)
            daily = daily_etf.loc[daily_etf["date"].between(start, end)].reset_index(drop=True)
            intraday = intraday_etf.loc[intraday_etf["date"].dt.normalize().between(start, end)].reset_index(drop=True)
            result = run_full_position_backtest(
                daily,
                {date: value for date, value in buy_schedule.items() if pd.Timestamp(start) <= date <= pd.Timestamp(end)},
                {},
                low_momentum_sell_schedule={date: value for date, value in sell_schedule.items() if pd.Timestamp(start) <= date <= pd.Timestamp(end)},
                trend_exit_schedule={date: value for date, value in trend_schedule.items() if pd.Timestamp(start) <= date <= pd.Timestamp(end)},
                intraday=intraday,
            )
            metrics = _metrics(result)
            rows.append({
                "window": window, "min_history": minimum_history(window), "stage": stage,
                "buy_signal_count": int(len(buys.loc[buys["date"].between(start, end)])),
                "sell_warning_count": int(len(sells.loc[sells["date"].between(start, end)])),
                "gap_rank_spearman_ic_5d": correlations[5], "gap_rank_spearman_ic_10d": correlations[10],
                **metrics,
            })
            result.nav.to_csv(output_dir / f"nav_{stage}_window_{window}.csv", index=False, encoding="utf-8-sig")
            result.trades.to_csv(output_dir / f"trades_{stage}_window_{window}.csv", index=False, encoding="utf-8-sig")
    summary = pd.DataFrame(rows)
    summary.to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(
        "# 0AMV乖离度滚动窗口影响研究\n\n"
        "比较100/200/300/400/500/750日窗口。买点最低历史样本保持窗口三分之一；卖点为同窗口P85与候选动量P20。收益在510300ETF上按原有卖点、5%止损与7%后实体低点止盈回测。\n\n"
        + summary.to_csv(index=False), encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf", type=Path, default=Path("data/backtest_data/510300.SH.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/factor_research_runs/amv_quantile_window_impact"))
    args = parser.parse_args()
    print(run_research(args.amv, args.etf, args.output).to_string(index=False))


if __name__ == "__main__":
    main()
