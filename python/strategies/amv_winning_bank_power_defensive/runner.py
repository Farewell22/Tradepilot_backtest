"""Rotate 512100 into equal bank and power ETF sleeves on a 0AMV exit."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
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
BANK = "512800.SH"
POWER = "561560.SH"
CODES = (PRIMARY, BANK, POWER)
BANK_SPLIT_EX_DATE = pd.Timestamp("2025-07-07")
BANK_SPLIT_RATIO = 2


@dataclass
class DefensiveResult:
    nav: pd.DataFrame
    trades: pd.DataFrame
    open_positions: dict[str, int]


def _buy_quantity(price: float, budget: float, fees: FeeConfig) -> int:
    quantity = int(budget / (price * (1 + fees.slippage_rate))) // 100 * 100
    while quantity > 0 and calc_buy_cost(price, quantity, fees)[1] > budget:
        quantity -= 100
    return quantity


def run_defensive_backtest(
    bars_by_code: dict[str, pd.DataFrame],
    amv_signals: pd.DataFrame,
    initial_cash: float = 200_000.0,
    fees: FeeConfig | None = None,
) -> DefensiveResult:
    """Use the existing 0AMV same-close model and split defense cash 50/50."""
    if set(bars_by_code) != set(CODES):
        raise ValueError(f"必须提供三只 ETF: {', '.join(CODES)}")
    if initial_cash <= 0:
        raise ValueError("初始资金必须大于 0")
    fees = fees or FeeConfig.etf_legacy()
    required = {"date", "buy_signal", "exit_ma10", "exit_macd"}
    if not required.issubset(amv_signals.columns):
        raise ValueError(f"0AMV 信号缺少列: {sorted(required - set(amv_signals.columns))}")
    signals = amv_signals.copy()
    signals["date"] = pd.to_datetime(signals["date"], errors="raise").dt.normalize()
    if signals["date"].duplicated().any():
        raise ValueError("0AMV 信号存在重复日期")
    signal_map = signals.set_index("date")
    bars = {code: _normalize_intraday(bars_by_code[code]) for code in CODES}
    sessions = {
        code: {date: day for date, day in frame.groupby(frame["date"].dt.normalize())}
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
    in_defense = False

    def sell(code: str, date: pd.Timestamp, price: float, reason: str,
             time: str = "15:00") -> None:
        nonlocal cash
        held = positions.pop(code)
        exec_price, proceeds = calc_sell_proceeds(price, held["quantity"], fees)
        cash += proceeds
        trade_rows.append({
            "date": date.strftime("%Y%m%d"), "time": time, "code": code,
            "side": "sell", "quantity": held["quantity"], "signal_price": price,
            "exec_price": exec_price, "cash_flow": proceeds, "reason": reason,
            "pnl": proceeds - held["buy_cost"],
            "pnl_pct": (proceeds / held["buy_cost"] - 1) * 100,
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
            "entry_session_index": session_index, "reference_price": exec_price,
            "profit_armed": False,
            "consolidation_applied": date >= CONSOLIDATION_DATE,
            "bank_split_applied": date >= BANK_SPLIT_EX_DATE,
        }
        trade_rows.append({
            "date": date.strftime("%Y%m%d"), "time": "15:00", "code": code,
            "side": "buy", "quantity": quantity, "signal_price": price,
            "exec_price": exec_price, "cash_flow": -cost, "reason": reason,
        })

    for session_index, date in enumerate(dates):
        day = {code: sessions[code][date].sort_values("date") for code in CODES}
        closes = {code: float(frame.iloc[-1]["close"]) for code, frame in day.items()}
        primary = day[PRIMARY]
        daily_open = float(primary.iloc[0]["open"])
        daily_high = float(primary["high"].max())

        if (BANK in positions and not positions[BANK]["bank_split_applied"]
                and date >= BANK_SPLIT_EX_DATE):
            positions[BANK]["quantity"] *= BANK_SPLIT_RATIO
            positions[BANK]["bank_split_applied"] = True
        if PRIMARY in positions:
            held = positions[PRIMARY]
            if (not held["consolidation_applied"] and held["entry_date"] < CONSOLIDATION_DATE
                    and date >= CONSOLIDATION_DATE):
                held["quantity"] = math.ceil(held["quantity"] * CONSOLIDATION_RATIO)
                held["reference_price"] /= CONSOLIDATION_RATIO
                held["consolidation_applied"] = True
                if previous_body_low is not None:
                    previous_body_low /= CONSOLIDATION_RATIO

        intraday_exit = False
        if PRIMARY in positions:
            held = positions[PRIMARY]
            stop_level = held["reference_price"] * 0.975
            trail_level = previous_body_low if held["profit_armed"] else None
            for bar in primary.to_dict("records"):
                open_price, low_price = float(bar["open"]), float(bar["low"])
                price: float | None = None
                reason = ""
                if open_price < stop_level:
                    price, reason = open_price, "hard_stop_2.5pct"
                elif trail_level is not None and open_price < trail_level:
                    price, reason = open_price, "profit_trail_body_break_5pct"
                elif trail_level is not None and low_price < trail_level:
                    price, reason = trail_level, "profit_trail_body_break_5pct"
                elif low_price < stop_level:
                    price, reason = stop_level, "hard_stop_2.5pct"
                if price is not None:
                    sell(PRIMARY, date, price, reason,
                         pd.Timestamp(bar["date"]).strftime("%H:%M"))
                    intraday_exit = True
                    break

        signal = signal_map.loc[date]
        exit_ma10, exit_macd = bool(signal["exit_ma10"]), bool(signal["exit_macd"])
        if exit_ma10 or exit_macd:
            reason = (
                "amv_close_below_ma10_and_macd_dead_cross" if exit_ma10 and exit_macd
                else "amv_close_below_ma10" if exit_ma10 else "amv_macd_dead_cross"
            )
            if PRIMARY in positions:
                sell(PRIMARY, date, closes[PRIMARY], reason)
            if not in_defense:
                budget = cash / 2
                buy(BANK, date, closes[BANK], budget, reason)
                buy(POWER, date, closes[POWER], budget, reason)
                in_defense = True
        elif not intraday_exit and bool(signal["buy_signal"]):
            for code in (BANK, POWER):
                if code in positions:
                    sell(code, date, closes[code], "amv_buy_signal_rotate_back")
            if PRIMARY not in positions:
                buy(PRIMARY, date, closes[PRIMARY], cash, "amv_buy_signal")
            if PRIMARY in positions:
                in_defense = False

        if PRIMARY in positions and positions[PRIMARY]["entry_date"] < date:
            if daily_high > positions[PRIMARY]["reference_price"] * 1.05:
                positions[PRIMARY]["profit_armed"] = True
        nav_rows.append({
            "date": date,
            "nav": cash + sum(held["quantity"] * closes[code] for code, held in positions.items()),
            "cash": cash, "invested": bool(positions),
            **{f"{code}_quantity": positions.get(code, {}).get("quantity", 0) for code in CODES},
        })
        previous_body_low = min(daily_open, closes[PRIMARY])

    return DefensiveResult(pd.DataFrame(nav_rows), pd.DataFrame(trade_rows),
                           {code: held["quantity"] for code, held in positions.items()})


def run_research(
    amv_path: Path,
    primary_path: Path,
    bank_path: Path,
    power_path: Path,
    output_dir: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    initial_cash: float = 200_000.0,
    fees: FeeConfig | None = None,
) -> dict:
    """Write strategy and original-cash baselines on identical trading days."""
    fees = fees or FeeConfig.etf_legacy()
    signals = generate_amv_signals(pd.read_csv(amv_path, encoding="utf-8-sig"))
    paths = {PRIMARY: primary_path, BANK: bank_path, POWER: power_path}
    bars = {code: _normalize_intraday(pd.read_csv(path, encoding="utf-8-sig"))
            for code, path in paths.items()}
    shared = set(signals["date"])
    for frame in bars.values():
        shared &= set(frame["date"].dt.normalize())
    if start_date:
        shared = {date for date in shared if date >= pd.to_datetime(start_date, format="%Y%m%d")}
    if end_date:
        shared = {date for date in shared if date <= pd.to_datetime(end_date, format="%Y%m%d")}
    if not shared:
        raise ValueError("所选区间没有 0AMV 与三只 ETF 的共同交易日")
    dates = sorted(shared)
    signals = signals.loc[signals["date"].isin(shared)].reset_index(drop=True)
    bars = {code: frame.loc[frame["date"].dt.normalize().isin(shared)].reset_index(drop=True)
            for code, frame in bars.items()}

    strategy = run_defensive_backtest(bars, signals, initial_cash, fees)
    original = run_full_position_backtest(bars[PRIMARY], signals, initial_cash, fees)
    sells = strategy.trades.loc[strategy.trades["side"] == "sell"] if not strategy.trades.empty else strategy.trades
    strategy_metrics = compute_performance_metrics(strategy.nav, sells, initial_cash,
                                                   bool(strategy.open_positions))
    original_metrics = compute_performance_metrics(original.nav, original.trades, initial_cash,
                                                   original.open_position is not None)
    metrics = {
        **strategy_metrics,
        "original_strategy": original_metrics,
        "start_date": dates[0].strftime("%Y%m%d"),
        "end_date": dates[-1].strftime("%Y%m%d"),
        "shared_sessions": len(dates),
        "fees": asdict(fees),
        "bank_split": {"record_date": "2025-07-04", "ex_date": "2025-07-07", "ratio": 2},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    strategy.nav.merge(original.nav[["date", "nav"]].rename(columns={"nav": "original_nav"}),
                       on="date").to_csv(output_dir / "nav.csv", index=False, encoding="utf-8-sig")
    strategy.trades.to_csv(output_dir / "trades.csv", index=False, encoding="utf-8-sig")
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = (
        "# 0AMV 离场后银行与电力 ETF 各半防守\n\n"
        f"区间：{dates[0].date()} 至 {dates[-1].date()}；共同交易日：{len(dates)}。\n\n"
        "| 方案 | 累计收益 | 年化收益 | 最大回撤 |\n"
        "| --- | ---: | ---: | ---: |\n"
        f"| 银行/电力 ETF 各半 | {strategy_metrics['total_return_pct']:.2f}% | "
        f"{strategy_metrics['annualized_return_pct']:.2f}% | {strategy_metrics['max_drawdown_pct']:.2f}% |\n"
        f"| 原策略持现金 | {original_metrics['total_return_pct']:.2f}% | "
        f"{original_metrics['annualized_return_pct']:.2f}% | {original_metrics['max_drawdown_pct']:.2f}% |\n\n"
        "0AMV 跌破 MA10 或 MACD 死叉时，以当时可用现金的各 50% 买入 512800.SH 与 561560.SH；"
        "下一次有效买入信号卖出两只防守 ETF，买回 512100.SH。防守期间不再平衡，不设独立止盈止损。"
        "512100 沿用 2.5% 盘中硬止损和盈利后跟踪止盈；盘中止损后，当天有 0AMV 离场信号仍进入防守。\n\n"
        "0AMV 日收盘信号按同日收盘价成交是理想化假设；三只 ETF 均按 ETF 费用和整百份交易。"
        "银行 ETF 于 2025-07-04 登记、2025-07-07 生效的 1:2 份额拆分已处理。"
        "两只 ETF 的 2023、2025 年年报显示 2022—2025 年未实施基金现金分配；区间内不另计成分股分红。"
        "仅使用三只 ETF 与 0AMV 均有数据的共同交易日。"
        "现金对照调用原版独立 runner；原版与防守分支在主仓盘中止损后同日能否按买入信号回补上有差异，"
        "不能把两者收益差全部归因于防守标的。"
        "未模拟涨跌停、停牌不可成交及尾盘流动性冲击。\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return metrics
