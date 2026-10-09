"""Backtest MA10>MA30 positive-gap buy tiers with existing AMV sell signals."""
from __future__ import annotations

from python.research.date_scope import scoped_ranges

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from python.factors.amv_buy_points import analyze_amv_buy_points
from python.factors.amv_gap import MIN_HISTORY, QUANTILE_LOOKBACK, classify_buy_point, generate_buy_signals
from python.strategies.etf_amv.strategy import normalize_etf_history, normalize_etf_intraday
from python.backtest.simulator import calc_buy_cost, calc_sell_proceeds
from python.backtest.broker import FeeConfig
from python.factor_research.data import load_amv_csv


INITIAL_CASH = 200_000.0
SAMPLES = {"train": ("2015-01-01", "2023-12-31"), "oos": ("2024-01-01", "2025-12-31")}
SCENARIOS = {
    "class_1_only": {"class_1"},
    "class_2_only": {"class_2"},
    "class_3_only": {"class_3"},
    "class_2_3_combined": {"class_2", "class_3"},
    "combined": {"class_1", "class_2", "class_3"},
}


def generate_trend_exit_signals(amv: pd.DataFrame) -> pd.DataFrame:
    """Emit the first MA10 <= MA30 date after an uptrend regime."""
    result = amv.loc[:, ["date", "close"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result["close"] = pd.to_numeric(result["close"], errors="raise")
    result = result.sort_values("date").reset_index(drop=True)
    result["ma10"] = result["close"].rolling(10, min_periods=10).mean()
    result["ma30"] = result["close"].rolling(30, min_periods=30).mean()
    crossed_down = (result["ma10"] <= result["ma30"]) & (result["ma10"].shift(1) > result["ma30"].shift(1))
    return result.loc[crossed_down, ["date"]].assign(exit_type="ma10_le_ma30")


def _next_session_schedule(
    signal_rows: pd.DataFrame,
    etf_dates: pd.Series,
    type_column: str,
) -> dict[pd.Timestamp, list[str]]:
    dates = pd.to_datetime(etf_dates).dt.normalize().drop_duplicates().sort_values().reset_index(drop=True)
    if dates.empty:
        return {}
    sessions = dates.to_numpy(dtype="datetime64[ns]")
    schedule: dict[pd.Timestamp, list[str]] = {}
    for row in signal_rows.to_dict("records"):
        signal_date = pd.Timestamp(row["date"]).normalize()
        if signal_date < dates.iloc[0]:
            continue
        index = sessions.searchsorted(signal_date.to_datetime64(), side="right")
        if index >= len(dates):
            continue
        execution = pd.Timestamp(dates.iloc[index]).normalize()
        values = row[type_column]
        if not isinstance(values, list):
            values = [values]
        schedule.setdefault(execution, []).extend(str(value) for value in values if value)
    return schedule


@dataclass
class BacktestResult:
    final_value: float
    nav: pd.DataFrame
    trades: pd.DataFrame
    ignored_buy_signals: int


def run_full_position_backtest(
    etf: pd.DataFrame,
    buy_schedule: dict[pd.Timestamp, str | list[str]],
    sell_schedule: dict[pd.Timestamp, list[str]],
    low_momentum_sell_schedule: dict[pd.Timestamp, list[str]] | None = None,
    trend_exit_schedule: dict[pd.Timestamp, list[str]] | None = None,
    intraday: pd.DataFrame | None = None,
    initial_cash: float = INITIAL_CASH,
    fees: FeeConfig | None = None,
) -> BacktestResult:
    """Use next-open signals, plus hard-stop and 60-minute profit-trail exits."""
    trend_exit_schedule = trend_exit_schedule or {}
    low_momentum_sell_schedule = low_momentum_sell_schedule or {}
    columns = ["date", "open", "close"] + (["low"] if "low" in etf.columns else []) + (["high"] if "high" in etf.columns else [])
    prices = etf.loc[:, columns].copy()
    if "low" not in prices.columns:
        prices["low"] = prices[["open", "close"]].min(axis=1)
    if "high" not in prices.columns:
        prices["high"] = prices[["open", "close"]].max(axis=1)
    prices["date"] = pd.to_datetime(prices["date"], errors="raise").dt.normalize()
    prices = prices.sort_values("date").reset_index(drop=True)
    intraday_by_date: dict[pd.Timestamp, pd.DataFrame] = {}
    if intraday is not None and not intraday.empty:
        minute_bars = intraday.loc[:, ["date", "open", "high", "low", "close"]].copy()
        minute_bars["date"] = pd.to_datetime(minute_bars["date"], errors="raise")
        for column in ("open", "high", "low", "close"):
            minute_bars[column] = pd.to_numeric(minute_bars[column], errors="raise")
        minute_bars = minute_bars.sort_values("date")
        for session_date, rows in minute_bars.groupby(minute_bars["date"].dt.normalize(), sort=False):
            intraday_by_date[pd.Timestamp(session_date)] = rows.reset_index(drop=True)
    cash = float(initial_cash)
    quantity = 0
    entry: dict | None = None
    trades: list[dict] = []
    nav_rows: list[dict] = []
    ignored = 0
    position_sequence = 0
    priority = {"class_3": 1, "class_2": 2, "class_1": 3}

    def exit_event(
        active_entry: dict,
        sell_quantity: int,
        sell_date: pd.Timestamp,
        signal_price: float,
        reason: str,
        day_index: int,
        position_after_quantity: int,
    ) -> dict:
        exec_price, proceeds = calc_sell_proceeds(signal_price, sell_quantity, fees)
        allocated_buy_cost = active_entry["buy_cost"] * sell_quantity / active_entry["buy_quantity"]
        return {
            **active_entry,
            "buy_cost": allocated_buy_cost,
            "sell_date": sell_date.strftime("%Y%m%d"),
            "sell_signal_price": signal_price,
            "sell_exec_price": exec_price,
            "sell_proceeds": proceeds,
            "sell_reason": reason,
            "sell_quantity": sell_quantity,
            "position_after_quantity": position_after_quantity,
            "is_partial_exit": position_after_quantity > 0,
            "pnl": proceeds - allocated_buy_cost,
            "pnl_pct": (proceeds / allocated_buy_cost - 1.0) * 100.0,
            "hold_days": int(day_index - active_entry["entry_day_index"]),
        }

    for day_index, row in prices.iterrows():
        date = pd.Timestamp(row["date"]).normalize()
        open_price, close_price = float(row["open"]), float(row["close"])
        sell_types = sorted(set(sell_schedule.get(date, [])))
        low_momentum_sell_types = sorted(set(low_momentum_sell_schedule.get(date, [])))
        trend_exit_types = sorted(set(trend_exit_schedule.get(date, [])))
        exit_day = bool(sell_types or trend_exit_types)
        if quantity and exit_day:
            sell_reason = (
                "sell_signal_" + "_".join(sell_types)
                if sell_types else "trend_exit_" + "_".join(trend_exit_types)
            )
            event = exit_event(entry, quantity, date, open_price, sell_reason, day_index, 0)
            trades.append(event)
            cash += event["sell_proceeds"]
            quantity = 0
            entry = None

        if quantity and low_momentum_sell_types:
            sell_quantity = quantity if len(low_momentum_sell_types) >= 2 else min(
                quantity, entry["buy_quantity"] // 2
            )
            position_after_quantity = quantity - sell_quantity
            suffix = "partial_exit" if position_after_quantity else "full_exit"
            sell_reason = "momentum_warning_" + "_".join(low_momentum_sell_types) + "_" + suffix
            event = exit_event(
                entry, sell_quantity, date, open_price, sell_reason, day_index, position_after_quantity
            )
            trades.append(event)
            cash += event["sell_proceeds"]
            quantity = position_after_quantity
            if quantity == 0:
                entry = None
                exit_day = True

        if quantity:
            previous_body_low = (
                min(float(prices.iloc[day_index - 1]["open"]), float(prices.iloc[day_index - 1]["close"]))
                if day_index > 0 else None
            )
            day_bars = intraday_by_date.get(date)
            if day_bars is None:
                day_bars = pd.DataFrame([{
                    "open": open_price, "high": float(row["high"]), "low": float(row["low"]), "close": close_price,
                }])
            for _, bar in day_bars.iterrows():
                stop_price = entry["buy_exec_price"] * 0.95
                trail_price = previous_body_low if entry.get("profit_armed") and previous_body_low is not None else None
                thresholds = [(stop_price, "stop_loss_5pct")] if day_index > entry["entry_day_index"] else []
                if trail_price is not None:
                    thresholds.append((trail_price, "profit_trail_body_break_7pct"))
                hit = [item for item in thresholds if float(bar["low"]) <= item[0]]
                if hit:
                    signal_price, reason = max(hit, key=lambda item: item[0])
                    signal_price = min(float(bar["open"]), signal_price)
                    event = exit_event(entry, quantity, date, signal_price, reason, day_index, 0)
                    trades.append(event)
                    cash += event["sell_proceeds"]
                    quantity = 0
                    entry = None
                    exit_day = True
                    break
                if float(bar["high"]) >= entry["buy_exec_price"] * 1.07:
                    entry["profit_armed"] = True

        signals = buy_schedule.get(date, [])
        if not isinstance(signals, list):
            signals = [signals] if signals else []
        if signals and exit_day:
            ignored += len(signals)
        elif signals and quantity:
            ignored += len(signals)
        elif signals:
            signal_type = max(signals, key=lambda value: priority[value])
            desired = int(cash / (open_price * 1.002)) // 100 * 100
            while desired > 0:
                exec_price, cost = calc_buy_cost(open_price, desired, fees)
                if cost <= cash:
                    break
                desired -= 100
            if desired > 0:
                cash -= cost
                quantity = desired
                entry = {
                    "buy_date": date.strftime("%Y%m%d"),
                    "buy_signal_price": open_price,
                    "buy_exec_price": exec_price,
                    "buy_quantity": quantity,
                    "buy_cost": cost,
                    "buy_signal_type": signal_type,
                    "entry_day_index": int(day_index),
                    "profit_armed": False,
                    "position_id": position_sequence,
                }
                position_sequence += 1
                entry_bars = intraday_by_date.get(date)
                entry_high = (
                    float(entry_bars["high"].max())
                    if entry_bars is not None and not entry_bars.empty else float(row["high"])
                )
                if entry_high >= entry["buy_exec_price"] * 1.07:
                    entry["profit_armed"] = True
        nav_rows.append({"date": date, "nav": cash + quantity * close_price})

    nav = pd.DataFrame(nav_rows)
    final_value = float(nav.iloc[-1]["nav"]) if not nav.empty else float(initial_cash)
    trades_frame = pd.DataFrame(trades)
    if not trades_frame.empty:
        trades_frame = trades_frame.drop(columns=["entry_day_index"])
    return BacktestResult(final_value, nav, trades_frame, ignored)


def _metrics(result: BacktestResult) -> dict:
    nav = result.nav["nav"]
    drawdown = nav / nav.cummax() - 1.0 if not nav.empty else pd.Series(dtype="float64")
    trades = result.trades
    closed_positions = (
        trades.groupby("position_id", as_index=False)[["pnl", "buy_cost"]].sum()
        if not trades.empty and "position_id" in trades.columns
        else trades
    )
    period_days = (
        (pd.Timestamp(result.nav.iloc[-1]["date"]) - pd.Timestamp(result.nav.iloc[0]["date"])).days
        if len(result.nav) > 1 else 0
    )
    annualized_return = (
        ((result.final_value / INITIAL_CASH) ** (365.0 / period_days) - 1.0) * 100.0
        if period_days > 0 else float("nan")
    )
    return {
        "final_value": result.final_value,
        "total_return_pct": (result.final_value / INITIAL_CASH - 1.0) * 100.0,
        "annualized_return_pct": annualized_return,
        "max_drawdown_pct": drawdown.min() * 100.0 if not drawdown.empty else 0.0,
        "closed_trade_count": int(len(closed_positions)),
        "win_rate_pct": (closed_positions["pnl"] > 0).mean() * 100.0 if not closed_positions.empty else float("nan"),
        "ignored_buy_signals": result.ignored_buy_signals,
    }


def run_research(amv_path: Path, etf_path: Path, output_dir: Path, fees: FeeConfig | None = None) -> pd.DataFrame:
    amv = load_amv_csv(amv_path)
    raw_etf = pd.read_csv(etf_path)
    daily_etf = normalize_etf_history(raw_etf)
    intraday_etf = normalize_etf_intraday(raw_etf)
    buy_signals = generate_buy_signals(amv)
    trend_exit_signals = generate_trend_exit_signals(amv)
    sell_points, _ = analyze_amv_buy_points(amv)
    buy_schedule = _next_session_schedule(buy_signals, daily_etf["date"], "signal_type")
    low_momentum_sell_schedule = _next_session_schedule(
        sell_points.loc[:, ["date", "sell_momentum_warning_types"]],
        daily_etf["date"],
        "sell_momentum_warning_types",
    )
    trend_exit_schedule = _next_session_schedule(trend_exit_signals, daily_etf["date"], "exit_type")
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for stage, (start, end) in scoped_ranges(SAMPLES).items():
        etf_stage = daily_etf.loc[daily_etf["date"].between(start, end)].reset_index(drop=True)
        intraday_stage = intraday_etf.loc[intraday_etf["date"].dt.normalize().between(start, end)].reset_index(drop=True)
        for name, enabled in SCENARIOS.items():
            stage_buys = {
                date: [kind for kind in kinds if kind in enabled]
                for date, kinds in buy_schedule.items()
                if pd.Timestamp(start) <= date <= pd.Timestamp(end) and any(kind in enabled for kind in kinds)
            }
            stage_low_momentum_sells = {
                date: kinds for date, kinds in low_momentum_sell_schedule.items()
                if pd.Timestamp(start) <= date <= pd.Timestamp(end)
            }
            stage_trend_exits = {
                date: kinds for date, kinds in trend_exit_schedule.items()
                if pd.Timestamp(start) <= date <= pd.Timestamp(end)
            }
            result = run_full_position_backtest(
                etf_stage,
                stage_buys,
                {},
                trend_exit_schedule=stage_trend_exits,
                intraday=intraday_stage,
                low_momentum_sell_schedule=stage_low_momentum_sells,
                fees=fees,
            )
            metrics = _metrics(result)
            rows.append({"stage": stage, "scenario": name, "entry_signal_count": sum(len(v) for v in stage_buys.values()), **metrics})
            result.trades.to_csv(output_dir / f"trades_{stage}_{name}.csv", index=False, encoding="utf-8-sig")
            result.nav.to_csv(output_dir / f"nav_{stage}_{name}.csv", index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(rows)
    summary.to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    buy_signals.to_csv(output_dir / "buy_signals.csv", index=False, encoding="utf-8-sig")
    report = [
        "# MA10高于MA30：MA10乖离度三档买点 + 低动量分批减仓回测",
        "",
        "买点：MA10 > MA30，按该状态下的750个历史有效观察值排名。一类为允许负乖离的浅回撤，二、三类要求gap10为正。",
        "一类为P30-P35且MA3上升；二类为P60-P80；三类为P40-P60。首次进入或向上升级时，下一ETF交易日开盘全仓买入。",
        "低动量减仓：MA10 > MA30，且gap10/gap20超过各自滚动P85、三日动量低于同类候选历史P20。",
        "单一低动量信号在下一ETF交易日开盘卖出初始买入数量的50%；同日一、二类同时出现则开盘清仓。",
        "退出优先级：MA10 <= MA30趋势失效；另从买入次日开始，ETF日内触及成本价-5%时硬止损。低动量减仓不阻止其余风控退出。",
        "盈利达到7%后，从下一根60分钟K线开始，若跌破前一日ETF K线实体最低点则止盈退出。",
        "本研究不使用止盈或最大持仓天数；期末持仓按收盘价估值。",
        "",
        summary.to_markdown(index=False, floatfmt=".2f"),
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf", type=Path, default=Path("data/backtest_data/510300.SH.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/backtest_runs/etf_510300_ma10_above_ma30_gap_signal"))
    args = parser.parse_args()
    print(run_research(args.amv, args.etf, args.output).to_string(index=False))


if __name__ == "__main__":
    main()
