"""Rotate 512100 into dividend and coal ETFs on a 0AMV MACD death cross."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from python.backtest.broker import FeeConfig, calc_buy_cost, calc_sell_proceeds
from python.strategies.amv_winning.runner import (
    CONSOLIDATION_DATE,
    CONSOLIDATION_RATIO,
    _normalize_intraday,
    compute_performance_metrics,
    generate_amv_signals,
    run_full_position_backtest,
)


PRIMARY = "512100.SH"
DIVIDEND = "510880.SH"
COAL = "515220.SH"
CODES = (PRIMARY, DIVIDEND, COAL)
COAL_SPLIT_EX_DATE = pd.Timestamp("2024-04-12")
COAL_SPLIT_RATIO = 2
# (code, record date, ex-dividend date, cash payment date, yuan per share)
DIVIDEND_EVENTS = (
    (DIVIDEND, "2021-01-15", "2021-01-18", "2021-01-21", 0.141),
    (DIVIDEND, "2022-01-14", "2022-01-17", "2022-01-20", 0.086),
    (DIVIDEND, "2023-01-13", "2023-01-16", "2023-01-19", 0.138),
    (DIVIDEND, "2024-01-22", "2024-01-23", "2024-01-26", 0.131),
    (DIVIDEND, "2025-01-20", "2025-01-21", "2025-01-24", 0.142),
    (COAL, "2021-12-24", "2021-12-27", "2021-12-30", 0.080),
    (COAL, "2022-12-26", "2022-12-27", "2022-12-30", 0.040),
    (COAL, "2023-12-27", "2023-12-28", "2024-01-03", 0.050),
    (COAL, "2024-12-23", "2024-12-24", "2024-12-27", 0.045),
    (COAL, "2025-12-23", "2025-12-24", "2025-12-29", 0.040),
)


@dataclass
class RotationResult:
    nav: pd.DataFrame
    trades: pd.DataFrame
    open_positions: dict[str, int]


def _buy_quantity(price: float, budget: float, fees: FeeConfig) -> int:
    unit_price = price * (1 + fees.slippage_rate)
    quantity = int(budget / unit_price) // 100 * 100
    while quantity > 0 and calc_buy_cost(price, quantity, fees)[1] > budget:
        quantity -= 100
    return quantity


def run_rotation_backtest(
    bars_by_code: dict[str, pd.DataFrame],
    amv_signals: pd.DataFrame,
    initial_cash: float = 200_000.0,
    fees: FeeConfig | None = None,
) -> RotationResult:
    """Apply the old strategy's same-close execution model to three ETFs."""
    fees = fees or FeeConfig.etf_legacy()
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if set(bars_by_code) != set(CODES):
        raise ValueError(f"必须提供三只 ETF: {', '.join(CODES)}")
    required_signals = {"date", "buy_signal", "exit_ma10", "exit_macd"}
    if not required_signals.issubset(amv_signals.columns):
        raise ValueError(f"0AMV 信号缺少列: {sorted(required_signals - set(amv_signals.columns))}")
    signals = amv_signals.copy()
    signals["date"] = pd.to_datetime(signals["date"]).dt.normalize()
    if signals["date"].duplicated().any():
        raise ValueError("0AMV 信号存在重复日期")
    signal_map = signals.set_index("date")
    bars = {code: _normalize_intraday(bars_by_code[code]) for code in CODES}
    sessions = {
        code: {date: day for date, day in frame.groupby(frame["date"].dt.normalize(), sort=True)}
        for code, frame in bars.items()
    }
    dates = sorted(set(signal_map.index).intersection(*(set(days) for days in sessions.values())))
    if not dates:
        raise ValueError("0AMV 与三只 ETF 没有共同交易日")

    cash = float(initial_cash)
    positions: dict[str, dict] = {}
    trade_rows: list[dict] = []
    nav_rows: list[dict] = []
    previous_body_low: float | None = None
    dividend_receivable = 0.0
    pending_dividends: list[dict] = []

    def sell(code: str, date: pd.Timestamp, price: float, reason: str, time: str = "15:00") -> None:
        nonlocal cash
        held = positions.pop(code)
        quantity = held["quantity"]
        exec_price, proceeds = calc_sell_proceeds(price, quantity, fees)
        cash += proceeds
        trade_rows.append({
            "date": date.strftime("%Y%m%d"), "time": time, "code": code, "side": "sell",
            "quantity": quantity, "signal_price": price, "exec_price": exec_price,
            "cash_flow": proceeds, "reason": reason,
            "dividend_income": held["dividend_income"],
            "pnl": proceeds - held["buy_cost"] + held["dividend_income"],
            "pnl_pct": (proceeds + held["dividend_income"] - held["buy_cost"]) / held["buy_cost"] * 100,
            "hold_sessions": session_index - held["entry_session_index"],
        })

    def buy(code: str, date: pd.Timestamp, price: float, budget: float, reason: str) -> None:
        nonlocal cash
        quantity = _buy_quantity(price, min(budget, cash), fees)
        if quantity == 0:
            return
        exec_price, cost = calc_buy_cost(price, quantity, fees)
        cash -= cost
        positions[code] = {
            "quantity": quantity, "buy_cost": cost, "entry_date": date,
            "entry_session_index": session_index,
            "reference_price": exec_price, "profit_armed": False,
            "consolidation_applied": date >= CONSOLIDATION_DATE,
            "coal_split_applied": date >= COAL_SPLIT_EX_DATE,
            "dividend_income": 0.0,
        }
        trade_rows.append({
            "date": date.strftime("%Y%m%d"), "time": "15:00", "code": code,
            "side": "buy", "quantity": quantity, "signal_price": price,
            "exec_price": exec_price, "cash_flow": -cost, "reason": reason,
        })

    for session_index, date in enumerate(dates):
        for entitlement in pending_dividends:
            if not entitlement["ex_applied"] and date >= entitlement["ex_date"]:
                dividend_receivable += entitlement["amount"]
                entitlement["ex_applied"] = True
            if not entitlement["paid"] and date >= entitlement["pay_date"]:
                cash += entitlement["amount"]
                dividend_receivable -= entitlement["amount"]
                entitlement["paid"] = True
        pending_dividends = [item for item in pending_dividends if not item["paid"]]
        day = {code: sessions[code][date].sort_values("date") for code in CODES}
        closes = {code: float(frame.iloc[-1]["close"]) for code, frame in day.items()}
        if COAL in positions and not positions[COAL]["coal_split_applied"] and date >= COAL_SPLIT_EX_DATE:
            positions[COAL]["quantity"] *= COAL_SPLIT_RATIO
            positions[COAL]["coal_split_applied"] = True
        primary = day[PRIMARY]
        daily_open = float(primary.iloc[0]["open"])
        daily_high = float(primary["high"].max())

        if PRIMARY in positions:
            held = positions[PRIMARY]
            if (not held["consolidation_applied"] and held["entry_date"] < CONSOLIDATION_DATE
                    and date >= CONSOLIDATION_DATE):
                held["quantity"] = math.ceil(held["quantity"] * CONSOLIDATION_RATIO)
                held["reference_price"] /= CONSOLIDATION_RATIO
                held["consolidation_applied"] = True
                if previous_body_low is not None:
                    previous_body_low /= CONSOLIDATION_RATIO
            stop_level = held["reference_price"] * 0.975
            trail_level = previous_body_low if held["profit_armed"] else None
            for bar in primary.to_dict("records"):
                bar_open, bar_low = float(bar["open"]), float(bar["low"])
                exit_price: float | None = None
                reason = ""
                if bar_open < stop_level:
                    exit_price, reason = bar_open, "hard_stop_2.5pct"
                elif trail_level is not None and bar_open < trail_level:
                    exit_price, reason = bar_open, "profit_trail_body_break_5pct"
                elif trail_level is not None and bar_low < trail_level:
                    exit_price, reason = trail_level, "profit_trail_body_break_5pct"
                elif bar_low < stop_level:
                    exit_price, reason = stop_level, "hard_stop_2.5pct"
                if exit_price is not None:
                    sell(PRIMARY, date, exit_price, reason, pd.Timestamp(bar["date"]).strftime("%H:%M"))
                    break

        signal = signal_map.loc[date]
        death_cross = bool(signal["exit_macd"])
        ma10_exit = bool(signal["exit_ma10"])
        buy_signal = bool(signal["buy_signal"])
        if death_cross:
            if PRIMARY in positions:
                sell(PRIMARY, date, closes[PRIMARY], "amv_macd_dead_cross_rotation")
            if DIVIDEND not in positions and COAL not in positions:
                budget = cash / 2
                buy(DIVIDEND, date, closes[DIVIDEND], budget, "amv_macd_dead_cross_rotation")
                buy(COAL, date, closes[COAL], budget, "amv_macd_dead_cross_rotation")
        elif buy_signal and not ma10_exit:
            for code in (DIVIDEND, COAL):
                if code in positions:
                    sell(code, date, closes[code], "amv_buy_signal_rotate_back")
            if PRIMARY not in positions:
                buy(PRIMARY, date, closes[PRIMARY], cash, "amv_buy_signal")
        elif ma10_exit and PRIMARY in positions:
            sell(PRIMARY, date, closes[PRIMARY], "amv_close_below_ma10")

        if PRIMARY in positions and positions[PRIMARY]["entry_date"] < date:
            if daily_high > positions[PRIMARY]["reference_price"] * 1.05:
                positions[PRIMARY]["profit_armed"] = True
        for code, record_date, ex_date, pay_date, per_share in DIVIDEND_EVENTS:
            if date == pd.Timestamp(record_date) and code in positions:
                amount = positions[code]["quantity"] * per_share
                positions[code]["dividend_income"] += amount
                pending_dividends.append({
                    "ex_date": pd.Timestamp(ex_date), "pay_date": pd.Timestamp(pay_date),
                    "amount": amount, "ex_applied": False, "paid": False,
                })
        nav_rows.append({
            "date": date, "nav": cash + dividend_receivable + sum(
                positions[code]["quantity"] * closes[code] for code in positions),
            "cash": cash, "dividend_receivable": dividend_receivable, "invested": bool(positions),
            **{f"{code}_quantity": positions.get(code, {}).get("quantity", 0) for code in CODES},
        })
        previous_body_low = min(daily_open, closes[PRIMARY])

    return RotationResult(pd.DataFrame(nav_rows), pd.DataFrame(trade_rows),
                          {code: held["quantity"] for code, held in positions.items()})


def run_research(
    amv_path: Path,
    primary_path: Path,
    dividend_path: Path,
    coal_path: Path,
    output_dir: Path,
    start_date: str | None = None,
    end_date: str | None = None,
    initial_cash: float = 200_000.0,
    fees: FeeConfig | None = None,
) -> dict:
    """Run rotation and original strategy on the same shared session dates."""
    fees = fees or FeeConfig.etf_legacy()
    amv = pd.read_csv(amv_path, encoding="utf-8-sig")
    signals = generate_amv_signals(amv)
    source_paths = {PRIMARY: primary_path, DIVIDEND: dividend_path, COAL: coal_path}
    bars = {code: _normalize_intraday(pd.read_csv(path, encoding="utf-8-sig"))
            for code, path in source_paths.items()}
    shared = set(signals["date"])
    for frame in bars.values():
        shared.intersection_update(frame["date"].dt.normalize().unique())
    if start_date:
        shared = {date for date in shared if date >= pd.to_datetime(start_date, format="%Y%m%d")}
    if end_date:
        shared = {date for date in shared if date <= pd.to_datetime(end_date, format="%Y%m%d")}
    if not shared:
        raise ValueError("所选区间没有 0AMV 与三只 ETF 的共同交易日")
    shared_dates = sorted(shared)
    signals = signals.loc[signals["date"].isin(shared_dates)].reset_index(drop=True)
    bars = {code: frame.loc[frame["date"].dt.normalize().isin(shared_dates)].reset_index(drop=True)
            for code, frame in bars.items()}
    rotation = run_rotation_backtest(bars, signals, initial_cash, fees)
    original = run_full_position_backtest(bars[PRIMARY], signals, initial_cash, fees)
    sells = rotation.trades.loc[rotation.trades["side"] == "sell"] if not rotation.trades.empty else pd.DataFrame()
    rotation_metrics = compute_performance_metrics(rotation.nav, sells, initial_cash, bool(rotation.open_positions))
    original_metrics = compute_performance_metrics(original.nav, original.trades, initial_cash, original.open_position is not None)
    metrics = {**rotation_metrics, "original_strategy": original_metrics,
               "start_date": shared_dates[0].strftime("%Y%m%d"),
               "end_date": shared_dates[-1].strftime("%Y%m%d"),
               "shared_sessions": len(shared_dates)}
    output_dir.mkdir(parents=True, exist_ok=True)
    rotation.nav.merge(original.nav[["date", "nav"]].rename(columns={"nav": "original_nav"}), on="date").to_csv(
        output_dir / "nav.csv", index=False, encoding="utf-8-sig")
    rotation.trades.to_csv(output_dir / "trades.csv", index=False, encoding="utf-8-sig")
    (output_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = (
        "# 0AMV 必胜策略：死叉切换红利与煤炭 ETF\n\n"
        f"区间：{shared_dates[0].date()}～{shared_dates[-1].date()}，共同交易日 {len(shared_dates)} 天。"
        f"轮动收益 {rotation_metrics['total_return_pct']:.2f}%，原策略同期收益 {original_metrics['total_return_pct']:.2f}%。\n\n"
        "死叉日切换至 510880.SH 与 515220.SH，各分配当时资金的 50%；下一次有效原买入信号切回 512100.SH。"
        "512100 的 MA10 退出、2.5% 止损及 5% 后移动止盈沿用原规则。防守 ETF 持有至切回信号，期间不设单独止损。\n\n"
        "0AMV 信号收盘后才能确认，本回测假设信号日同一收盘价成交，属于理想化口径；费用使用 ETF 口径。"
        "回测按公开权益分派记录计入红利和煤炭 ETF 的现金分红，并处理煤炭 ETF 于 2024-04-12 生效的 1:2 份额拆分。"
        "仅使用三只 ETF 均有行情的共同交易日。\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return metrics
