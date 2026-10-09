"""Compare structural filters that prevent immediate 0AMV re-entry after momentum sells."""
from __future__ import annotations

from python.research.date_scope import scoped_ranges

import argparse
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd

from python.factors.amv_buy_points import analyze_amv_buy_points
from python.strategies.etf_amv.strategy import normalize_etf_history, normalize_etf_intraday
from python.research.amv.ma10_above_ma30_gap.study import (
    INITIAL_CASH,
    MIN_HISTORY,
    QUANTILE_LOOKBACK,
    SAMPLES,
    _metrics,
    _next_session_schedule,
    generate_buy_signals,
    generate_trend_exit_signals,
    run_full_position_backtest,
)
from python.factor_research.data import load_amv_csv


SCENARIOS = {
    "original": "原始二/三类买点",
    "ma3_rising": "MA3向上",
    "ma3_rising_momentum_positive": "MA3向上 + 3日动量>0",
    "quality_momentum": "MA3向上 + 动量>0 + 动量>P50 + 二类P60-P75",
    "p40_reset": "卖点后需重新回落P40",
    "quality_momentum_p40_reset": "质量动量过滤 + 卖点后P40重置",
}
RESET_RANK = 0.40
FAST_REENTRY_SESSIONS = 30


def p40_reset_eligibility(states: pd.DataFrame) -> pd.Series:
    """Mark dates eligible after each momentum sell has subsequently cooled to gap10 P40."""
    required = {"gap10_rank", "has_momentum_sell"}
    missing = required.difference(states.columns)
    if missing:
        raise ValueError(f"状态数据缺少列: {', '.join(sorted(missing))}")
    required_reset = False
    eligible: list[bool] = []
    for row in states.itertuples():
        if bool(row.has_momentum_sell):
            required_reset = True
        if required_reset and pd.notna(row.gap10_rank) and float(row.gap10_rank) <= RESET_RANK:
            required_reset = False
        eligible.append(not required_reset)
    return pd.Series(eligible, index=states.index, dtype=bool)


def build_indicator_states(amv: pd.DataFrame, sell_points: pd.DataFrame) -> pd.DataFrame:
    """Calculate only-prior-history ranks and independent momentum/re-entry state variables."""
    states = amv.loc[:, ["date", "close"]].copy()
    states["date"] = pd.to_datetime(states["date"], errors="raise").dt.normalize()
    states["close"] = pd.to_numeric(states["close"], errors="raise")
    states = states.sort_values("date").reset_index(drop=True)
    states["ma3"] = states["close"].rolling(3, min_periods=3).mean()
    states["ma10"] = states["close"].rolling(10, min_periods=10).mean()
    states["ma30"] = states["close"].rolling(30, min_periods=30).mean()
    states["ma3_rising"] = states["ma3"] > states["ma3"].shift(1)
    states["momentum_3"] = states["close"].pct_change(3)
    states["momentum_3_p50_60"] = states["momentum_3"].rolling(60, min_periods=60).quantile(0.50).shift(1)
    states["gap10"] = states["close"] / states["ma10"] - 1.0
    states["gap10_rank"] = np.nan
    history: deque[float] = deque(maxlen=QUANTILE_LOOKBACK)
    for index, row in states.iterrows():
        if pd.notna(row["ma10"]) and row["ma10"] > row["ma30"]:
            gap = float(row["gap10"])
            if len(history) >= MIN_HISTORY:
                values = list(history)
                states.at[index, "gap10_rank"] = (
                    sum(value < gap for value in values) + 0.5 * sum(value == gap for value in values)
                ) / len(values)
            history.append(gap)
    sells = sell_points.loc[sell_points["sell_momentum_warning_types"].map(bool), "date"]
    sell_dates = set(pd.to_datetime(sells, errors="raise").dt.normalize())
    states["has_momentum_sell"] = states["date"].isin(sell_dates)
    states["p40_reset_eligible"] = p40_reset_eligibility(states)
    return states


def filter_buy_signals(buy_signals: pd.DataFrame, states: pd.DataFrame, scenario: str) -> pd.DataFrame:
    """Keep class-2/class-3 signals only when a selected scenario's entry filters pass."""
    if scenario not in SCENARIOS:
        raise ValueError(f"未知研究情景: {scenario}")
    signals = buy_signals.loc[buy_signals["signal_type"].isin(["class_2", "class_3"])].copy()
    signals = signals.merge(
        states[["date", "ma3_rising", "momentum_3", "momentum_3_p50_60", "p40_reset_eligible"]],
        on="date", how="left",
    )
    keep = pd.Series(True, index=signals.index)
    if scenario in {"ma3_rising", "ma3_rising_momentum_positive", "quality_momentum", "quality_momentum_p40_reset"}:
        keep &= signals["ma3_rising"].eq(True)
    if scenario in {"ma3_rising_momentum_positive", "quality_momentum", "quality_momentum_p40_reset"}:
        keep &= signals["momentum_3"] > 0.0
    if scenario in {"quality_momentum", "quality_momentum_p40_reset"}:
        keep &= signals["momentum_3"] > signals["momentum_3_p50_60"]
        keep &= ~((signals["signal_type"] == "class_2") & (signals["gap10_rank"] >= 0.75))
    if scenario in {"p40_reset", "quality_momentum_p40_reset"}:
        keep &= signals["p40_reset_eligible"].eq(True)
    return signals.loc[keep].reset_index(drop=True)


def _fast_reentry_count(signals: pd.DataFrame, states: pd.DataFrame) -> int:
    sell_indices = states.index[states["has_momentum_sell"]].to_numpy()
    if not len(sell_indices) or signals.empty:
        return 0
    index_by_date = pd.Series(states.index.to_numpy(), index=states["date"])
    count = 0
    for date in signals["date"]:
        index = index_by_date.get(pd.Timestamp(date))
        if index is None:
            continue
        prior = sell_indices[sell_indices < index]
        if len(prior) and int(index - prior[-1]) <= FAST_REENTRY_SESSIONS:
            count += 1
    return count


def run_research(amv_path: Path, etf_path: Path, output_dir: Path) -> pd.DataFrame:
    amv = load_amv_csv(amv_path)
    raw_etf = pd.read_csv(etf_path)
    daily_etf = normalize_etf_history(raw_etf)
    intraday_etf = normalize_etf_intraday(raw_etf)
    sell_points, _ = analyze_amv_buy_points(amv)
    states = build_indicator_states(amv, sell_points)
    base_buys = generate_buy_signals(amv)
    trend_exits = generate_trend_exit_signals(amv)
    low_schedule = _next_session_schedule(sell_points[["date", "sell_momentum_warning_types"]], daily_etf["date"], "sell_momentum_warning_types")
    trend_schedule = _next_session_schedule(trend_exits, daily_etf["date"], "exit_type")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict] = []
    for scenario in SCENARIOS:
        signals = filter_buy_signals(base_buys, states, scenario)
        signals.to_csv(output_dir / f"signals_{scenario}.csv", index=False, encoding="utf-8-sig")
        buy_schedule = _next_session_schedule(signals, daily_etf["date"], "signal_type")
        for stage, (start, end) in scoped_ranges(SAMPLES).items():
            daily = daily_etf.loc[daily_etf["date"].between(start, end)].reset_index(drop=True)
            intraday = intraday_etf.loc[intraday_etf["date"].dt.normalize().between(start, end)].reset_index(drop=True)
            result = run_full_position_backtest(
                daily,
                {date: kinds for date, kinds in buy_schedule.items() if pd.Timestamp(start) <= date <= pd.Timestamp(end)},
                {},
                low_momentum_sell_schedule={date: kinds for date, kinds in low_schedule.items() if pd.Timestamp(start) <= date <= pd.Timestamp(end)},
                trend_exit_schedule={date: kinds for date, kinds in trend_schedule.items() if pd.Timestamp(start) <= date <= pd.Timestamp(end)},
                intraday=intraday,
            )
            metrics = _metrics(result)
            stage_signals = signals.loc[signals["date"].between(start, end)]
            summary_rows.append({
                "scenario": scenario, "scenario_name": SCENARIOS[scenario], "stage": stage,
                "candidate_signal_count": int(len(stage_signals)),
                "fast_reentry_signal_count_30_sessions": _fast_reentry_count(stage_signals, states),
                **metrics,
            })
            result.nav.to_csv(output_dir / f"nav_{stage}_{scenario}.csv", index=False, encoding="utf-8-sig")
            result.trades.to_csv(output_dir / f"trades_{stage}_{scenario}.csv", index=False, encoding="utf-8-sig")
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    states.to_csv(output_dir / "indicator_states.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(
        "# 0AMV 买点再入场过滤对照研究\n\n"
        "统一采用二类/三类买点、下一交易日开盘、低动量分批减仓、MA10<=MA30清仓、5%止损和7%后实体低点止盈。P40重置为每次低动量卖点后，gap10滚动排名重新降至P40以下才恢复买点资格。\n\n"
        + summary.to_csv(index=False), encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf", type=Path, default=Path("data/backtest_data/510300.SH.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/factor_research_runs/amv_buy_reentry_filters"))
    args = parser.parse_args()
    print(run_research(args.amv, args.etf, args.output).to_string(index=False))


if __name__ == "__main__":
    main()
