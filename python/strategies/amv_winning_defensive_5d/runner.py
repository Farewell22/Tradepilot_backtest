"""Compare cash, half dividend/coal, and severe-cross dividend defense."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from python.backtest.broker import FeeConfig, calc_buy_cost, calc_sell_proceeds
from python.strategies.amv_winning.runner import (
    CONSOLIDATION_DATE, CONSOLIDATION_RATIO, _normalize_intraday,
    compute_performance_metrics, generate_amv_signals,
)
from python.strategies.amv_winning_rotation.runner import (
    PRIMARY, DIVIDEND, COAL, CODES, COAL_SPLIT_EX_DATE, COAL_SPLIT_RATIO,
    DIVIDEND_EVENTS, _buy_quantity,
)


MODES = ("cash", "half", "severe_red")
SEVERE_THRESHOLD = -0.04
DEFENSIVE_SESSIONS = 5
BENCHMARK_DIVIDEND = (PRIMARY, "2025-01-14", "2025-01-15", "2025-01-20", 0.037)


@dataclass
class VariantResult:
    nav: pd.DataFrame
    trades: pd.DataFrame
    open_positions: dict[str, int]


def run_variant(
    bars_by_code: dict[str, pd.DataFrame], amv_signals: pd.DataFrame, mode: str,
    initial_cash: float = 200_000.0, fees: FeeConfig | None = None,
) -> VariantResult:
    """Execute close-known AMV signals at the next common session's open."""
    if mode not in MODES or set(bars_by_code) != set(CODES):
        raise ValueError("模式或 ETF 数据不完整")
    if initial_cash <= 0:
        raise ValueError("initial_cash 必须为正")
    fees = fees or FeeConfig.etf_legacy()
    required = {"date", "buy_signal", "exit_macd", "exit_ma10", "momentum_3"}
    if not required.issubset(amv_signals):
        raise ValueError(f"0AMV 信号缺少列: {sorted(required - set(amv_signals))}")
    signals = amv_signals.copy()
    signals["date"] = pd.to_datetime(signals["date"]).dt.normalize()
    if signals["date"].duplicated().any():
        raise ValueError("0AMV 信号存在重复日期")
    signal_map = signals.set_index("date")
    bars = {code: _normalize_intraday(frame) for code, frame in bars_by_code.items()}
    sessions = {code: {day: frame.sort_values("date") for day, frame in bars[code].groupby(bars[code]["date"].dt.normalize())}
                for code in CODES}
    dates = sorted(set(signal_map.index).intersection(*(set(sessions[code]) for code in CODES)))
    if not dates:
        raise ValueError("0AMV 与三只 ETF 没有共同交易日")

    cash = float(initial_cash)
    receivable = 0.0
    positions: dict[str, dict] = {}
    pending_dividends: list[dict] = []
    trades: list[dict] = []
    nav_rows: list[dict] = []
    pending_action: str | None = None
    previous_body_low: float | None = None

    def sell(code: str, date: pd.Timestamp, price: float, reason: str, time: str) -> None:
        nonlocal cash
        held = positions.pop(code)
        execution, proceeds = calc_sell_proceeds(price, held["quantity"], fees)
        cash += proceeds
        trades.append({
            "date": date.strftime("%Y%m%d"), "time": time, "code": code, "side": "sell",
            "quantity": held["quantity"], "signal_price": price, "exec_price": execution,
            "cash_flow": proceeds, "reason": reason,
            "dividend_income": held["dividend_income"],
            "pnl": proceeds + held["dividend_income"] - held["buy_cost"],
            "pnl_pct": (proceeds + held["dividend_income"]) / held["buy_cost"] * 100 - 100,
            "hold_sessions": session_index - held["entry_index"],
        })

    def buy(code: str, date: pd.Timestamp, price: float, budget: float, reason: str) -> None:
        nonlocal cash
        quantity = _buy_quantity(price, min(budget, cash), fees)
        if quantity == 0:
            return
        execution, cost = calc_buy_cost(price, quantity, fees)
        cash -= cost
        positions[code] = {
            "quantity": quantity, "buy_cost": cost, "entry_date": date,
            "entry_index": session_index, "reference_price": execution,
            "profit_armed": False, "defensive_age": 0,
            "consolidation_applied": date >= CONSOLIDATION_DATE,
            "coal_split_applied": date >= COAL_SPLIT_EX_DATE,
            "dividend_income": 0.0,
        }
        trades.append({
            "date": date.strftime("%Y%m%d"), "time": "open", "code": code,
            "side": "buy", "quantity": quantity, "signal_price": price,
            "exec_price": execution, "cash_flow": -cost, "reason": reason,
        })

    for session_index, date in enumerate(dates):
        day = {code: sessions[code][date] for code in CODES}
        opens = {code: float(frame.iloc[0]["open"]) for code, frame in day.items()}
        closes = {code: float(frame.iloc[-1]["close"]) for code, frame in day.items()}
        for entitlement in pending_dividends:
            if not entitlement["ex_applied"] and date >= entitlement["ex_date"]:
                receivable += entitlement["amount"]
                entitlement["ex_applied"] = True
            if not entitlement["paid"] and date >= entitlement["pay_date"]:
                cash += entitlement["amount"]
                receivable -= entitlement["amount"]
                entitlement["paid"] = True
        pending_dividends = [item for item in pending_dividends if not item["paid"]]

        if COAL in positions and not positions[COAL]["coal_split_applied"] and date >= COAL_SPLIT_EX_DATE:
            positions[COAL]["quantity"] *= COAL_SPLIT_RATIO
            positions[COAL]["coal_split_applied"] = True
        if PRIMARY in positions and not positions[PRIMARY]["consolidation_applied"] and date >= CONSOLIDATION_DATE:
            positions[PRIMARY]["quantity"] = math.ceil(positions[PRIMARY]["quantity"] * CONSOLIDATION_RATIO)
            positions[PRIMARY]["reference_price"] /= CONSOLIDATION_RATIO
            positions[PRIMARY]["consolidation_applied"] = True
            if previous_body_low is not None:
                previous_body_low /= CONSOLIDATION_RATIO

        if pending_action == "death":
            for code in tuple(positions):
                sell(code, date, opens[code], "amv_macd_dead_cross", "open")
            if mode == "half":
                budget = cash / 2
                buy(DIVIDEND, date, opens[DIVIDEND], budget, "death_cross_half")
                buy(COAL, date, opens[COAL], budget, "death_cross_half")
            elif mode == "severe_red" and bool(signal_map.loc[dates[session_index - 1], "momentum_3"] <= SEVERE_THRESHOLD):
                buy(DIVIDEND, date, opens[DIVIDEND], cash, "severe_death_cross")
        elif pending_action == "buy":
            for code in (DIVIDEND, COAL):
                if code in positions:
                    sell(code, date, opens[code], "amv_buy_rotate_back", "open")
            if PRIMARY not in positions:
                buy(PRIMARY, date, opens[PRIMARY], cash, "amv_buy_signal")
        elif pending_action == "ma_exit" and PRIMARY in positions:
            sell(PRIMARY, date, opens[PRIMARY], "amv_close_below_ma10", "open")

        if PRIMARY in positions:
            held = positions[PRIMARY]
            stop_level = held["reference_price"] * 0.975
            trail_level = previous_body_low if held["profit_armed"] else None
            for bar in day[PRIMARY].to_dict("records"):
                price_open, price_low = float(bar["open"]), float(bar["low"])
                if price_open < stop_level:
                    exit_price, reason = price_open, "hard_stop_2.5pct"
                elif trail_level is not None and price_open < trail_level:
                    exit_price, reason = price_open, "profit_trail_body_break_5pct"
                elif trail_level is not None and price_low < trail_level:
                    exit_price, reason = trail_level, "profit_trail_body_break_5pct"
                elif price_low < stop_level:
                    exit_price, reason = stop_level, "hard_stop_2.5pct"
                else:
                    continue
                sell(PRIMARY, date, exit_price, reason, pd.Timestamp(bar["date"]).strftime("%H:%M"))
                break

        for code in (DIVIDEND, COAL):
            if code in positions:
                positions[code]["defensive_age"] += 1
                if positions[code]["defensive_age"] >= DEFENSIVE_SESSIONS:
                    sell(code, date, closes[code], "defensive_5_session_exit", "15:00")

        if PRIMARY in positions and positions[PRIMARY]["entry_date"] < date:
            if float(day[PRIMARY]["high"].max()) > positions[PRIMARY]["reference_price"] * 1.05:
                positions[PRIMARY]["profit_armed"] = True
        for code, record_date, ex_date, pay_date, per_share in (*DIVIDEND_EVENTS, BENCHMARK_DIVIDEND):
            if date == pd.Timestamp(record_date) and code in positions:
                amount = positions[code]["quantity"] * per_share
                positions[code]["dividend_income"] += amount
                pending_dividends.append({
                    "ex_date": pd.Timestamp(ex_date), "pay_date": pd.Timestamp(pay_date),
                    "amount": amount, "ex_applied": False, "paid": False,
                })

        nav_rows.append({
            "date": date, "nav": cash + receivable + sum(
                positions[code]["quantity"] * closes[code] for code in positions),
            "cash": cash, "dividend_receivable": receivable, "invested": bool(positions),
            **{f"{code}_quantity": positions.get(code, {}).get("quantity", 0) for code in CODES},
        })
        signal = signal_map.loc[date]
        pending_action = (
            "death" if bool(signal["exit_macd"]) else
            "ma_exit" if bool(signal["exit_ma10"]) else
            "buy" if bool(signal["buy_signal"]) else None
        )
        previous_body_low = min(opens[PRIMARY], closes[PRIMARY])

    return VariantResult(pd.DataFrame(nav_rows), pd.DataFrame(trades),
                         {code: held["quantity"] for code, held in positions.items()})


def _segment_metrics(nav: pd.DataFrame, start: str, end: str, initial_cash: float) -> dict:
    segment = nav.loc[nav["date"].between(pd.Timestamp(start), pd.Timestamp(end)), "nav"]
    if segment.empty:
        return {"sessions": 0, "return_pct": None, "max_drawdown_pct": None}
    first_index = segment.index[0]
    starting_nav = float(nav.loc[first_index - 1, "nav"]) if first_index > 0 else initial_cash
    values = pd.concat([pd.Series([starting_nav]), segment.reset_index(drop=True)], ignore_index=True)
    return {"sessions": len(segment), "return_pct": (values.iloc[-1] / starting_nav - 1) * 100,
            "max_drawdown_pct": ((values / values.cummax()) - 1).min() * 100}


def run_research(
    amv_path: Path, primary_path: Path, dividend_path: Path, coal_path: Path,
    output_dir: Path, start_date: str | None = None, end_date: str | None = None,
    initial_cash: float = 200_000.0, fees: FeeConfig | None = None,
) -> dict:
    fees = fees or FeeConfig.etf_legacy()
    signals = generate_amv_signals(pd.read_csv(amv_path, encoding="utf-8-sig"))
    signals["momentum_3"] = signals["close"].pct_change(3)
    paths = {PRIMARY: primary_path, DIVIDEND: dividend_path, COAL: coal_path}
    bars = {code: _normalize_intraday(pd.read_csv(path, encoding="utf-8-sig")) for code, path in paths.items()}
    shared = set(signals["date"])
    for frame in bars.values():
        shared.intersection_update(frame["date"].dt.normalize().unique())
    if start_date:
        shared = {date for date in shared if date >= pd.to_datetime(start_date, format="%Y%m%d")}
    if end_date:
        shared = {date for date in shared if date <= pd.to_datetime(end_date, format="%Y%m%d")}
    if not shared:
        raise ValueError("所选区间没有 0AMV 与三只 ETF 的共同交易日")
    dates = sorted(shared)
    signals = signals.loc[signals["date"].isin(dates)].reset_index(drop=True)
    bars = {code: frame.loc[frame["date"].dt.normalize().isin(dates)].reset_index(drop=True)
            for code, frame in bars.items()}
    results = {mode: run_variant(bars, signals, mode, initial_cash, fees) for mode in MODES}
    metrics = {}
    output_dir.mkdir(parents=True, exist_ok=True)
    nav = pd.DataFrame({"date": results["cash"].nav["date"]})
    for mode, result in results.items():
        sells = result.trades.loc[result.trades["side"] == "sell"] if not result.trades.empty else pd.DataFrame()
        metrics[mode] = {
            **compute_performance_metrics(result.nav, sells, initial_cash, bool(result.open_positions)),
            "train": _segment_metrics(result.nav, "2020-03-02", "2023-12-31", initial_cash),
            "oos": _segment_metrics(result.nav, "2024-01-01", "2025-12-31", initial_cash),
        }
        nav[f"{mode}_nav"] = result.nav["nav"]
        result.trades.to_csv(output_dir / f"trades_{mode}.csv", index=False, encoding="utf-8-sig")
    nav.to_csv(output_dir / "nav.csv", index=False, encoding="utf-8-sig")
    payload = {
        "start_date": dates[0].strftime("%Y%m%d"), "end_date": dates[-1].strftime("%Y%m%d"),
        "shared_sessions": len(dates), "initial_cash": initial_cash,
        "execution": "AMV close-known signal -> next common ETF session open; defensive expiry -> fifth session close",
        "severe_threshold": SEVERE_THRESHOLD, "defensive_sessions": DEFENSIVE_SESSIONS,
        "modes": metrics,
    }
    (output_dir / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# 0AMV 必胜策略：严重死叉红利防守（5 日）", "",
        f"区间 {dates[0].date()} 至 {dates[-1].date()}，共同交易日 {len(dates)} 天。",
        "0AMV 收盘信号在下一共同交易日开盘执行；严重死叉为三日动量 ≤ -4%。防守仓最多持有五个交易日，",
        "第五日收盘退出；有效 0AMV 买入信号可在次日开盘提前切回 512100.SH。", "",
        "| 模式 | 总收益 | 最大回撤 | 训练期收益 | 样本外收益 |", "| --- | ---: | ---: | ---: | ---: |",
    ]
    for mode in MODES:
        m = metrics[mode]
        train_return = f"{m['train']['return_pct']:.2f}%" if m["train"]["return_pct"] is not None else "—"
        oos_return = f"{m['oos']['return_pct']:.2f}%" if m["oos"]["return_pct"] is not None else "—"
        report.append(f"| {mode} | {m['total_return_pct']:.2f}% | {m['max_drawdown_pct']:.2f}% | "
                      f"{train_return} | {oos_return} |")
    report.extend(["", "三组均使用 ETF 佣金、滑点、整百份交易及同一交易日。主仓沿用 2.5% 硬止损和盈利后的前日实体低点止盈。",
                   "现金分红及煤炭 ETF 拆分计入净值。该回测不等于先前同日收盘成交的原策略结果。", ""])
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    return payload
