"""Backtest close-entry 0AMV with conditional bank ETF or stock holdings."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from python.backtest.broker import FeeConfig, calc_buy_cost, calc_sell_proceeds
from python.factors.z_indicators import compute_dynamic_weekly_kdj


DEFAULT_AMV_PATH = Path("data/backtest_data/0AMV-260612.csv")
DEFAULT_ETF_PATH = Path("data/backtest_data/ETF_60min_2005_2025/512100.SH.csv")
DEFAULT_BANK_PATH = Path("data/backtest_data/ETF_60min_2005_2025/512800.SH.csv")
DEFAULT_STOCK_DATA_DIR = Path("data/backtest_data/5m_price")
DEFAULT_STOCK_DIVIDENDS_PATH = Path(__file__).resolve().parents[1] / "amv_winning_defensive/dividends_601288.csv"
DEFAULT_OUTPUT_DIR = Path("data/backtest_runs/0amv_winning_512100")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "report.md"
COMMISSION_RATE = 0.0003
MIN_COMMISSION = 5.0
SLIPPAGE_RATE = 0.001
CONSOLIDATION_DATE = pd.Timestamp("2022-09-02")
CONSOLIDATION_RATIO = 0.36555
PRIMARY = "512100.SH"
BANK = "512800.SH"
AGRICULTURAL_BANK = "601288.SH"
STOCK_BANK_CODES = frozenset({AGRICULTURAL_BANK, "601939.SH", "600036.SH"})
BANK_SPLIT_DATE = pd.Timestamp("2025-07-07")
BANK_SPLIT_RATIO = 2


@dataclass
class BacktestResult:
    nav: pd.DataFrame
    trades: pd.DataFrame
    final_value: float
    open_position: dict | None


def generate_amv_signals(amv: pd.DataFrame) -> pd.DataFrame:
    """Calculate the strategy's close-known buy and exit signals."""
    required = {"date", "close"}
    missing = required.difference(amv.columns)
    if missing:
        raise ValueError(f"0AMV 数据缺少列: {', '.join(sorted(missing))}")
    result = amv.loc[:, ["date", "close"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result["close"] = pd.to_numeric(result["close"], errors="raise")
    result = result.sort_values("date").reset_index(drop=True)
    if result["date"].duplicated().any() or (result["close"] <= 0).any():
        raise ValueError("0AMV 数据存在重复日期或非正收盘价")

    result["day_return"] = result["close"].pct_change()
    result["two_day_return"] = result["close"].pct_change(2)
    result["ma5"] = result["close"].rolling(5).mean()
    result["ma10"] = result["close"].rolling(10).mean()
    ema12 = result["close"].ewm(span=12, adjust=False).mean()
    ema26 = result["close"].ewm(span=26, adjust=False).mean()
    result["dif"] = ema12 - ema26
    result["dea"] = result["dif"].ewm(span=9, adjust=False).mean()
    result["buy_signal"] = (
        ((result["day_return"] >= 0.04) | (result["two_day_return"] >= 0.04))
        & (result["close"] >= result["ma5"])
    )
    result["exit_ma10"] = result["close"] < result["ma10"]
    result["exit_macd"] = (
        (result["dif"] < result["dea"])
        & (result["dif"].shift(1) >= result["dea"].shift(1))
    )
    return result


def _normalize_intraday(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "时间": "date", "开盘价": "open", "最高价": "high", "最低价": "low",
        "收盘价": "close", "成交量": "volume",
    }
    result = frame.rename(columns=aliases).copy()
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required.difference(result.columns)
    if missing:
        raise ValueError(f"ETF 数据缺少列: {', '.join(sorted(missing))}")
    result = result.loc[:, ["date", "open", "high", "low", "close", "volume"]]
    result["date"] = pd.to_datetime(result["date"], errors="raise")
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="raise")
    if result["date"].duplicated().any() or (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("ETF 数据存在重复时间或非正价格")
    result = result.sort_values("date").reset_index(drop=True)
    session_volume = result.groupby(result["date"].dt.normalize())["volume"].transform("sum")
    return result.loc[session_volume > 0].reset_index(drop=True)


def _buy_cost(signal_price: float, quantity: int, fees: FeeConfig | None = None) -> tuple[float, float, float]:
    fees = fees or FeeConfig.etf_legacy()
    exec_price, cost = calc_buy_cost(signal_price, quantity, fees)
    commission = max(fees.min_commission, exec_price * quantity * fees.commission_rate)
    return exec_price, cost, commission


def _sell_proceeds(signal_price: float, quantity: int, fees: FeeConfig | None = None) -> tuple[float, float, float]:
    fees = fees or FeeConfig.etf_legacy()
    exec_price, proceeds = calc_sell_proceeds(signal_price, quantity, fees)
    commission = max(fees.min_commission, exec_price * quantity * fees.commission_rate)
    return exec_price, proceeds, commission


def run_full_position_backtest(
    intraday: pd.DataFrame,
    amv_signals: pd.DataFrame,
    initial_cash: float = 200_000.0,
    fees: FeeConfig | None = None,
) -> BacktestResult:
    """Preserve the original cash-only strategy for existing consumers."""
    return _run_position_backtest(intraday, amv_signals, initial_cash, fees)


def run_bank_kdj_backtest(
    intraday: pd.DataFrame,
    bank_intraday: pd.DataFrame,
    amv_signals: pd.DataFrame,
    bank_weekly_j: pd.Series,
    initial_cash: float = 200_000.0,
    fees: FeeConfig | None = None,
    *,
    bank_take_profit: bool | None = None,
    bank_code: str = BANK,
    bank_fees: FeeConfig | None = None,
    dividends: dict[pd.Timestamp, float] | None = None,
) -> BacktestResult:
    """Observe bank J after every primary exit; primary entry takes priority."""
    if not np.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("初始资金必须为有限正数")
    if bank_code not in STOCK_BANK_CODES | {BANK}:
        raise ValueError(f"不支持的银行标的: {bank_code}")
    if bank_take_profit is None:
        bank_take_profit = True
    if bank_fees is None and bank_code in STOCK_BANK_CODES:
        primary_fees = fees or FeeConfig.etf_legacy()
        bank_fees = FeeConfig.stock_legacy().with_overrides(
            commission_rate=primary_fees.commission_rate, min_commission=primary_fees.min_commission,
            slippage_rate=primary_fees.slippage_rate,
        )
    return _run_position_backtest(
        intraday, amv_signals, initial_cash, fees,
        bank_intraday=bank_intraday, bank_weekly_j=bank_weekly_j,
        bank_take_profit=bank_take_profit,
        bank_code=bank_code, bank_fees=bank_fees, dividends=dividends,
    )


def _run_position_backtest(
    intraday: pd.DataFrame,
    amv_signals: pd.DataFrame,
    initial_cash: float,
    fees: FeeConfig | None,
    *,
    bank_intraday: pd.DataFrame | None = None,
    bank_weekly_j: pd.Series | None = None,
    bank_take_profit: bool = True,
    bank_code: str = BANK,
    bank_fees: FeeConfig | None = None,
    dividends: dict[pd.Timestamp, float] | None = None,
) -> BacktestResult:
    """Share primary fills and accounting between cash and bank variants."""
    bars = _normalize_intraday(intraday)
    fees = fees or FeeConfig.etf_legacy()
    bank_fees = bank_fees or fees
    stock_enabled = bank_intraday is not None and bank_code in STOCK_BANK_CODES
    dividend_map = {pd.Timestamp(date).normalize(): float(amount)
                    for date, amount in (dividends or {}).items()}
    if any(pd.isna(date) or not np.isfinite(amount) or amount <= 0 for date, amount in dividend_map.items()):
        raise ValueError("分红表包含缺失日期或非有限正数金额")
    dividend_total = 0.0
    signals = amv_signals.copy()
    signals["date"] = pd.to_datetime(signals["date"], errors="raise").dt.normalize()
    if signals["date"].duplicated().any():
        raise ValueError("0AMV 信号存在重复日期")
    signal_map = signals.set_index("date")
    bank_enabled = bank_intraday is not None
    sessions = list(bars.groupby(bars["date"].dt.normalize(), sort=True))
    bank_sessions: dict[pd.Timestamp, pd.DataFrame] = {}
    weekly_j = pd.Series(dtype=float)
    if bank_enabled:
        bank_bars = _normalize_intraday(bank_intraday)
        bank_sessions = dict(tuple(bank_bars.groupby(bank_bars["date"].dt.normalize(), sort=True)))
        missing = [date for date, _ in sessions if date not in bank_sessions]
        if missing:
            raise ValueError(f"银行标的 {bank_code} 缺少交易日行情: " + ", ".join(date.strftime("%Y%m%d") for date in missing[:10]))
        if bank_weekly_j is None:
            raise ValueError("必须提供银行 ETF 动态周线 J")
        weekly_j = pd.to_numeric(bank_weekly_j.copy(), errors="raise")
        weekly_j.index = pd.to_datetime(weekly_j.index, errors="raise").normalize()
        if weekly_j.index.has_duplicates:
            raise ValueError("银行 ETF 周线 J 存在重复日期")
        missing_j = [date for date, _ in sessions if date not in weekly_j.index]
        if missing_j:
            raise ValueError("银行 ETF 缺少动态周线 J: " + ", ".join(date.strftime("%Y%m%d") for date in missing_j[:10]))

    cash = float(initial_cash)
    position: dict | None = None
    trades: list[dict] = []
    nav_rows: list[dict] = []
    previous_body_low: float | None = None
    bank_observing = False
    bank_sold_today = False

    def sell(price: float, reason: str, time: str = "15:00") -> None:
        nonlocal cash, position, bank_observing, bank_sold_today
        held = position
        trade_fees = fees if held["code"] == PRIMARY else bank_fees
        exec_price, proceeds, commission = _sell_proceeds(price, held["quantity"], trade_fees)
        dividend_income = held.get("dividend_income", 0.0)
        cash += proceeds
        trades.append({
            **held["trade"],
            "sell_date": session_date.strftime("%Y%m%d"), "sell_time": time,
            "sell_signal_price": price, "sell_exec_price": exec_price,
            "sell_quantity": held["quantity"], "sell_commission": commission,
            "sell_proceeds": proceeds, "sell_reason": reason,
            "pnl": proceeds + dividend_income - held["trade"]["buy_cost"],
            "pnl_pct": ((proceeds + dividend_income) / held["trade"]["buy_cost"] - 1) * 100,
            "hold_sessions": session_index - held["entry_session_index"],
        })
        if stock_enabled:
            trades[-1].update(
                dividend_income=dividend_income,
                sell_stamp_duty=exec_price * held["quantity"] * trade_fees.stamp_duty_rate,
                sell_transfer_fee=exec_price * held["quantity"] * trade_fees.transfer_fee_rate,
            )
        if held["code"] == PRIMARY:
            bank_observing = True
        else:
            bank_sold_today = True
        position = None

    def buy(code: str, price: float, j: float) -> None:
        nonlocal cash, position, bank_observing
        trade_fees = fees if code == PRIMARY else bank_fees
        exec_price = price * (1 + trade_fees.slippage_rate)
        quantity = int(cash / exec_price) // 100 * 100
        while quantity > 0:
            exec_price, cost, commission = _buy_cost(price, quantity, trade_fees)
            if cost <= cash:
                break
            quantity -= 100
        if quantity <= 0:
            return
        cash -= cost
        trade = {
            "buy_date": session_date.strftime("%Y%m%d"), "buy_time": "15:00",
            "buy_signal_price": price, "buy_exec_price": exec_price,
            "buy_quantity": quantity, "buy_commission": commission, "buy_cost": cost,
        }
        if bank_enabled:
            trade.update(code=code, buy_reason="amv_buy_signal" if code == PRIMARY else "bank_weekly_j_below_10",
                         buy_weekly_j=j if code == bank_code else np.nan)
        if stock_enabled:
            trade["buy_transfer_fee"] = exec_price * quantity * trade_fees.transfer_fee_rate
        position = {
            "code": code, "entry_date": session_date, "quantity": quantity,
            "entry_session_index": session_index, "reference_price": exec_price,
            "profit_armed": False, "consolidation_applied": session_date >= CONSOLIDATION_DATE,
            "bank_split_applied": session_date >= BANK_SPLIT_DATE, "trade": trade,
        }
        if stock_enabled:
            position["dividend_income"] = 0.0
        if code == PRIMARY:
            bank_observing = False

    for session_index, (session_date, day_bars) in enumerate(sessions):
        bank_sold_today = False
        day_bars = day_bars.sort_values("date")
        daily_open = float(day_bars.iloc[0]["open"])
        daily_close = float(day_bars.iloc[-1]["close"])
        daily_high = float(day_bars["high"].max())
        j = float(weekly_j.loc[session_date]) if bank_enabled else np.nan
        bank_day = bank_sessions[session_date] if bank_enabled else None
        bank_close = float(bank_day.iloc[-1]["close"]) if bank_enabled else 0.0

        if (stock_enabled and position is not None and position["code"] == bank_code
                and position["entry_date"] < session_date and session_date in dividend_map):
            income = position["quantity"] * dividend_map[session_date]
            cash += income
            position["dividend_income"] += income
            dividend_total += income

        if position is not None and position["code"] == PRIMARY:
            if (not position["consolidation_applied"]
                    and position["entry_date"] < CONSOLIDATION_DATE
                    and session_date >= CONSOLIDATION_DATE):
                position["quantity"] = math.ceil(position["quantity"] * CONSOLIDATION_RATIO)
                position["reference_price"] /= CONSOLIDATION_RATIO
                position["consolidation_applied"] = True
                if previous_body_low is not None:
                    previous_body_low /= CONSOLIDATION_RATIO
            trail_level = previous_body_low if position["profit_armed"] else None
            stop_level = position["reference_price"] * 0.975
            for bar in day_bars.to_dict("records"):
                open_price, low_price = float(bar["open"]), float(bar["low"])
                sell_price: float | None = None
                sell_reason = ""
                if open_price < stop_level:
                    sell_price, sell_reason = open_price, "hard_stop_2.5pct"
                elif trail_level is not None and open_price < trail_level:
                    sell_price, sell_reason = open_price, "profit_trail_body_break_5pct"
                elif trail_level is not None and low_price < trail_level:
                    sell_price, sell_reason = trail_level, "profit_trail_body_break_5pct"
                elif low_price < stop_level:
                    sell_price, sell_reason = stop_level, "hard_stop_2.5pct"
                if sell_price is not None:
                    sell(sell_price, sell_reason, pd.Timestamp(bar["date"]).strftime("%H:%M"))
                    break

        if position is not None and position["code"] == bank_code:
            if bank_code == BANK and not position["bank_split_applied"] and session_date >= BANK_SPLIT_DATE:
                position["quantity"] *= BANK_SPLIT_RATIO
                position["reference_price"] /= BANK_SPLIT_RATIO
                position["bank_split_applied"] = True
            if bank_take_profit and position["entry_date"] < session_date:
                target = position["reference_price"] * 1.08
                if stock_enabled:
                    target = math.ceil(target * 100 - 1e-10) / 100
                for bar in bank_day.to_dict("records"):
                    open_price, high_price = float(bar["open"]), float(bar["high"])
                    if open_price >= target or high_price >= target:
                        sell(open_price if open_price >= target else target, "bank_take_profit_8pct",
                             pd.Timestamp(bar["date"]).strftime("%H:%M"))
                        break

        signal = signal_map.loc[session_date] if session_date in signal_map.index else None
        exit_ma10 = bool(signal["exit_ma10"]) if signal is not None else False
        exit_macd = bool(signal["exit_macd"]) if signal is not None else False
        has_close_exit = exit_ma10 or exit_macd
        if position is not None and position["code"] == PRIMARY and has_close_exit:
            reason = (
                "amv_close_below_ma10_and_macd_dead_cross" if exit_ma10 and exit_macd
                else "amv_close_below_ma10" if exit_ma10 else "amv_macd_dead_cross"
            )
            sell(daily_close, reason)

        buy_signal = bool(signal["buy_signal"]) if signal is not None else False
        valid_primary_entry = buy_signal and not has_close_exit
        if valid_primary_entry:
            if position is not None and position["code"] == bank_code:
                sell(bank_close, "amv_buy_signal_rotate_back")
            if position is None:
                buy(PRIMARY, daily_close, j)
        elif (bank_enabled and position is None and bank_observing
              and not bank_sold_today and np.isfinite(j) and j < 10):
            buy(bank_code, bank_close, j)

        if position is not None and position["code"] == PRIMARY and position["entry_date"] < session_date:
            if daily_high > position["reference_price"] * 1.05:
                position["profit_armed"] = True

        held_close = bank_close if position is not None and position["code"] == bank_code else daily_close
        nav = cash + (position["quantity"] * held_close if position is not None else 0.0)
        row = {
            "date": session_date, "nav": nav, "cash": cash,
            "position_quantity": position["quantity"] if position is not None and position["code"] == PRIMARY else 0,
            "invested": position is not None,
        }
        if bank_enabled:
            row.update(bank_quantity=position["quantity"] if position is not None and position["code"] == bank_code else 0,
                       position_code=position["code"] if position is not None else "",
                       bank_weekly_j=j, bank_observing=bank_observing)
        if stock_enabled:
            row["dividend_income"] = dividend_total
        nav_rows.append(row)
        previous_body_low = min(daily_open, daily_close)

    nav_frame = pd.DataFrame(nav_rows)
    trades_frame = pd.DataFrame(trades)
    if bank_enabled and trades_frame.empty:
        trades_frame = pd.DataFrame(columns=[
            "buy_date", "buy_time", "buy_signal_price", "buy_exec_price",
            "buy_quantity", "buy_commission", "buy_cost", "code", "buy_reason", "buy_weekly_j",
            "sell_date", "sell_time", "sell_signal_price", "sell_exec_price",
            "sell_quantity", "sell_commission", "sell_proceeds", "sell_reason", "pnl", "pnl_pct", "hold_sessions",
        ])
        if stock_enabled:
            for column in ("buy_transfer_fee", "sell_transfer_fee", "sell_stamp_duty", "dividend_income"):
                trades_frame[column] = pd.Series(dtype=float)
    final_value = float(nav_frame.iloc[-1]["nav"]) if not nav_frame.empty else float(initial_cash)
    public_position = None if position is None else {
        "entry_date": position["entry_date"], "quantity": position["quantity"],
        "reference_price": position["reference_price"],
    }
    if bank_enabled and public_position is not None:
        public_position["code"] = position["code"]
        if stock_enabled:
            public_position["dividend_income"] = position["dividend_income"]
    return BacktestResult(nav_frame, trades_frame, final_value, public_position)


def compute_performance_metrics(
    nav: pd.DataFrame,
    trades: pd.DataFrame,
    initial_cash: float,
    has_open_position: bool,
) -> dict:
    """Compute calendar-time returns and trade statistics."""
    if nav.empty:
        return {
            "initial_cash": float(initial_cash), "final_nav": float(initial_cash),
            "total_return_pct": 0.0, "annualized_return_pct": 0.0,
            "max_drawdown_pct": 0.0, "sharpe_ratio": 0.0,
            "closed_trade_count": 0, "win_count": 0, "loss_count": 0,
            "win_rate_pct": 0.0, "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
            "profit_loss_ratio": 0.0, "avg_hold_sessions": 0.0,
            "exposure_pct": 0.0, "has_open_position": bool(has_open_position),
        }
    values = nav["nav"].astype(float)
    final_nav = float(values.iloc[-1])
    total_return = final_nav / initial_cash - 1
    days = (pd.Timestamp(nav.iloc[-1]["date"]) - pd.Timestamp(nav.iloc[0]["date"])).days
    annualized = (final_nav / initial_cash) ** (365.0 / days) - 1 if days > 0 and final_nav > 0 else 0.0
    drawdown = values / values.cummax().clip(lower=float(initial_cash)) - 1
    daily_returns = values.pct_change()
    daily_returns.iloc[0] = values.iloc[0] / initial_cash - 1
    sharpe = (
        float(daily_returns.mean() / daily_returns.std(ddof=1) * np.sqrt(243))
        if len(daily_returns) > 1 and daily_returns.std(ddof=1) > 0 else 0.0
    )
    wins = trades.loc[trades["pnl"] > 0] if not trades.empty else trades
    losses = trades.loc[trades["pnl"] <= 0] if not trades.empty else trades
    avg_win = float(wins["pnl_pct"].mean()) if not wins.empty else 0.0
    avg_loss = float(losses["pnl_pct"].mean()) if not losses.empty else 0.0
    return {
        "initial_cash": float(initial_cash), "final_nav": final_nav,
        "total_return_pct": total_return * 100, "annualized_return_pct": annualized * 100,
        "max_drawdown_pct": float(drawdown.min() * 100), "sharpe_ratio": sharpe,
        "closed_trade_count": int(len(trades)), "win_count": int(len(wins)),
        "loss_count": int(len(losses)),
        "win_rate_pct": float(len(wins) / len(trades) * 100) if len(trades) else 0.0,
        "avg_win_pct": avg_win, "avg_loss_pct": avg_loss,
        "profit_loss_ratio": abs(avg_win / avg_loss) if avg_loss < 0 else 0.0,
        "avg_hold_sessions": float(trades["hold_sessions"].mean()) if not trades.empty and "hold_sessions" in trades else 0.0,
        "exposure_pct": float(nav["invested"].mean() * 100) if "invested" in nav else 0.0,
        "has_open_position": bool(has_open_position),
    }


def _annual_returns(nav: pd.DataFrame, initial_cash: float, label: str) -> pd.DataFrame:
    if nav.empty:
        return pd.DataFrame(columns=["year", label])
    frame = nav.loc[:, ["date", "nav"]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["daily_return"] = frame["nav"].pct_change()
    frame.loc[frame.index[0], "daily_return"] = frame.iloc[0]["nav"] / initial_cash - 1
    annual = frame.groupby(frame["date"].dt.year)["daily_return"].apply(lambda values: (1 + values).prod() - 1)
    return annual.mul(100).rename(label).rename_axis("year").reset_index()


def _buy_and_hold(daily: pd.DataFrame, initial_cash: float, fees: FeeConfig | None = None) -> pd.DataFrame:
    fees = fees or FeeConfig.etf_legacy()
    cash = float(initial_cash)
    first_close = float(daily.iloc[0]["close"])
    exec_price = first_close * (1 + fees.slippage_rate)
    quantity = int(cash / exec_price) // 100 * 100
    while quantity > 0:
        _, cost, _ = _buy_cost(first_close, quantity, fees)
        if cost <= cash:
            break
        quantity -= 100
    cash -= cost
    adjusted = daily.iloc[0]["date"] >= CONSOLIDATION_DATE
    rows: list[dict] = []
    for row in daily.to_dict("records"):
        date = pd.Timestamp(row["date"])
        if not adjusted and date >= CONSOLIDATION_DATE:
            quantity = math.ceil(quantity * CONSOLIDATION_RATIO)
            adjusted = True
        rows.append({"date": date, "nav": cash + quantity * float(row["close"]), "invested": True})
    return pd.DataFrame(rows)


def _markdown_metrics(strategy: dict, benchmark: dict, original: dict) -> str:
    rows = [
        ("总收益率", strategy["total_return_pct"], original["total_return_pct"], benchmark["total_return_pct"]),
        ("年化收益率", strategy["annualized_return_pct"], original["annualized_return_pct"], benchmark["annualized_return_pct"]),
        ("最大回撤", strategy["max_drawdown_pct"], original["max_drawdown_pct"], benchmark["max_drawdown_pct"]),
        ("夏普比率", strategy["sharpe_ratio"], original["sharpe_ratio"], benchmark["sharpe_ratio"]),
    ]
    lines = ["| 指标 | 改造后策略 | 原纯现金策略 | 买入持有基准 |", "|---|---:|---:|---:|"]
    lines.extend(f"| {name} | {left:.2f} | {middle:.2f} | {right:.2f} |" for name, left, middle, right in rows)
    return "\n".join(lines)


def run_research(
    amv_path: Path,
    etf_path: Path,
    output_dir: Path,
    report_path: Path,
    initial_cash: float = 200_000.0,
    start_date: str | None = None,
    end_date: str | None = None,
    fees: FeeConfig | None = None,
    *,
    bank_path: Path = DEFAULT_BANK_PATH,
    bank_take_profit: bool | None = None,
    bank_code: str = BANK,
    stock_data_dir: Path = DEFAULT_STOCK_DATA_DIR,
    stock_dividends_path: Path = DEFAULT_STOCK_DIVIDENDS_PATH,
    bank_fees: FeeConfig | None = None,
) -> dict:
    """Run the bank variant and retain the same-input cash-only baseline."""
    fees = fees or FeeConfig.etf_legacy()
    amv = pd.read_csv(amv_path, encoding="utf-8-sig")
    bars = _normalize_intraday(pd.read_csv(etf_path, encoding="utf-8-sig"))
    if bank_code not in {BANK, AGRICULTURAL_BANK}:
        raise ValueError(f"不支持的银行标的: {bank_code}")
    stock_enabled = bank_code == AGRICULTURAL_BANK
    bank_take_profit = True if bank_take_profit is None else bank_take_profit
    bank_label = "农业银行" if stock_enabled else "银行 ETF"
    signals = generate_amv_signals(amv)
    session_dates = pd.Index(bars["date"].dt.normalize().unique())
    signals = signals.loc[signals["date"].isin(session_dates)].reset_index(drop=True)
    if start_date is not None:
        signals = signals.loc[signals["date"] >= pd.to_datetime(start_date, format="%Y%m%d")]
    if end_date is not None:
        signals = signals.loc[signals["date"] <= pd.to_datetime(end_date, format="%Y%m%d")]
    if signals.empty:
        raise ValueError("0AMV 与 ETF 数据没有共同交易日")
    first_date, last_date = signals["date"].min(), signals["date"].max()
    bars = bars.loc[bars["date"].dt.normalize().between(first_date, last_date)].reset_index(drop=True)

    dividends = {}
    stock_audit = None
    if stock_enabled:
        from python.strategies.amv_winning.bank_stock import (
            AUDITED_END, HISTORY_START, load_stock_dividends, load_stock_history,
        )
        if first_date < HISTORY_START:
            raise ValueError("农业银行周线预热行情和分红核对始于 2019 年")
        if stock_dividends_path.resolve() == DEFAULT_STOCK_DIVIDENDS_PATH.resolve() and last_date > AUDITED_END:
            raise ValueError("默认农业银行分红表只核对到 20251231，请提供完整的新分红表")
        bank_bars, stock_audit = load_stock_history(stock_data_dir, last_date)
        dividends = load_stock_dividends(stock_dividends_path)
        bank_fees = bank_fees or FeeConfig.stock_legacy().with_overrides(
            commission_rate=fees.commission_rate, min_commission=fees.min_commission,
            slippage_rate=fees.slippage_rate,
        )
    else:
        bank_bars = _normalize_intraday(pd.read_csv(bank_path, encoding="utf-8-sig"))
        bank_fees = bank_fees or fees

    # Preserve all pre-start bank candles for indicator warm-up.
    bank_history = bank_bars.loc[bank_bars["date"].dt.normalize() <= last_date]
    bank_daily = bank_history.assign(session=bank_history["date"].dt.normalize()).groupby("session").agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).reset_index().rename(columns={"session": "date"})
    bank_kdj = compute_dynamic_weekly_kdj(
        bank_daily, splits=None if stock_enabled else {BANK_SPLIT_DATE: BANK_SPLIT_RATIO},
        cash_dividends=dividends if stock_enabled else None,
    )
    bank_j = bank_kdj.set_index("date")["J"]
    trading_bank_bars = bank_bars.loc[bank_bars["date"].dt.normalize().between(first_date, last_date)]
    result = run_bank_kdj_backtest(bars, trading_bank_bars, signals, bank_j, initial_cash, fees,
                                  bank_take_profit=bank_take_profit, bank_code=bank_code,
                                  bank_fees=bank_fees, dividends=dividends)
    original = run_full_position_backtest(bars, signals, initial_cash, fees)

    daily = (
        bars.assign(session=bars["date"].dt.normalize())
        .groupby("session", as_index=False)
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        .rename(columns={"session": "date"})
    )
    benchmark_nav = _buy_and_hold(daily, initial_cash, fees)
    strategy_metrics = compute_performance_metrics(
        result.nav, result.trades, initial_cash, result.open_position is not None
    )
    original_metrics = compute_performance_metrics(
        original.nav, original.trades, initial_cash, original.open_position is not None
    )
    benchmark_metrics = compute_performance_metrics(benchmark_nav, pd.DataFrame(), initial_cash, True)
    bank_trades = result.trades.loc[result.trades["code"] == bank_code]
    bank_nav = result.nav.assign(invested=result.nav["bank_quantity"] > 0)
    bank_metrics = compute_performance_metrics(
        bank_nav, bank_trades, initial_cash,
        result.open_position is not None and result.open_position["code"] == bank_code,
    )
    # Bank statistics describe its trades/exposure, not a separate funded portfolio.
    bank_metrics = {key: bank_metrics[key] for key in (
        "closed_trade_count", "win_count", "loss_count", "win_rate_pct",
        "avg_win_pct", "avg_loss_pct", "avg_hold_sessions", "exposure_pct", "has_open_position"
    )}
    bank_metrics["realized_pnl"] = float(bank_trades["pnl"].sum())
    if stock_enabled:
        bank_metrics["dividend_income"] = float(result.nav.iloc[-1]["dividend_income"])
    open_position = None if result.open_position is None else {
        **result.open_position, "entry_date": result.open_position["entry_date"].strftime("%Y%m%d")
    }
    parameters = {
        "primary_etf": PRIMARY, "bank_code": bank_code, "bank_etf": None if stock_enabled else BANK,
        "weekly_kdj": [9, 3, 3], "weekly_kdj_mode": "dynamic_as_of_close",
        "bank_entry_j_lt": 10, "bank_watch_start": "after_any_primary_sell",
        "bank_take_profit_pct": 8 if bank_take_profit else None,
        "bank_take_profit_basis": "buy_execution_price" if bank_take_profit else None,
        "bank_stop_loss": None, "bank_reentry": "next_session_close" if bank_take_profit else "after_primary_exit",
        "primary_entry_priority": True, "bank_split_date": None if stock_enabled else BANK_SPLIT_DATE.strftime("%Y%m%d"),
        "bank_split_ratio": None if stock_enabled else BANK_SPLIT_RATIO,
    }
    metrics = {**strategy_metrics, "benchmark": benchmark_metrics, "original_strategy": original_metrics,
               "bank": bank_metrics, "open_position": open_position, "parameters": parameters,
               "fees": asdict(fees), "execution_mode": "legacy_same_close_idealized"}
    if stock_enabled:
        parameters.update(bank_stock=bank_code, indicator_price_basis="forward_adjusted_cash_dividends_as_of_date",
                          execution_price_basis="raw", dividend_booking="ex_date_previous_close_entitlement",
                          dividend_tax_mode="not_modeled", stock_fee_mode="fixed_legacy_rates",
                          bank_take_profit_tick=.01 if bank_take_profit else None)
        metrics["bank_fees"] = asdict(bank_fees)

    nav = result.nav.copy()
    nav["return_pct"] = (nav["nav"] / initial_cash - 1) * 100
    nav["drawdown_pct"] = (nav["nav"] / nav["nav"].cummax().clip(lower=float(initial_cash)) - 1) * 100
    nav = nav.merge(benchmark_nav.loc[:, ["date", "nav"]].rename(columns={"nav": "benchmark_nav"}), on="date")
    nav = nav.merge(original.nav.loc[:, ["date", "nav"]].rename(columns={"nav": "original_nav"}), on="date")
    annual = _annual_returns(result.nav, initial_cash, "strategy_return_pct").merge(
        _annual_returns(original.nav, initial_cash, "original_strategy_return_pct"), on="year", how="outer"
    ).merge(_annual_returns(benchmark_nav, initial_cash, "benchmark_return_pct"), on="year", how="outer")

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if stock_enabled:
        from python.strategies.amv_winning.bank_stock import snapshot_stock_inputs
        snapshot_stock_inputs(output_dir, bank_history, stock_dividends_path, stock_audit,
                              amv_path=amv_path, primary_path=etf_path)
    nav.to_csv(output_dir / "nav.csv", index=False, encoding="utf-8-sig")
    result.trades.to_csv(output_dir / "trades.csv", index=False, encoding="utf-8-sig")
    original.nav.to_csv(output_dir / "original_nav.csv", index=False, encoding="utf-8-sig")
    original_trades = original.trades if not original.trades.empty else pd.DataFrame(
        columns=[column for column in result.trades.columns if column not in {"code", "buy_reason", "buy_weekly_j"}]
    )
    original_trades.to_csv(output_dir / "original_trades.csv", index=False, encoding="utf-8-sig")
    bank_kdj.loc[bank_kdj["date"].between(first_date, last_date)].to_csv(
        output_dir / "bank_weekly_kdj.csv", index=False, encoding="utf-8-sig"
    )
    annual.to_csv(output_dir / "annual_returns.csv", index=False, encoding="utf-8-sig")
    (output_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "strategy_config.json").write_text(
        json.dumps(parameters, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    exit_counts = result.trades["sell_reason"].value_counts().to_dict()
    bank_rule = (
        "银行 ETF 以实际买入成交价上涨 8% 盘中止盈，无止损，J 回升不卖出。止盈当天不回买银行，最早下一交易日收盘再次检查 J<10；有效主仓进场信号始终优先。目标价不包含卖出费用，净收益可能低于 8%。"
        if bank_take_profit else
        "银行 ETF 不设固定止盈、无止损，J 回升不卖出；仅在主仓出现有效进场信号时卖出全部银行 ETF，并按原规则买回主仓。"
    )
    bank_rule = bank_rule.replace("银行 ETF", bank_label)
    if stock_enabled:
        bank_rule += " 股票止盈目标价向上取整到 0.01 元。" if bank_take_profit else ""
    corporate_action_rule = (
        "农行原始行情与成交额/成交量均价核对，成交和估值使用未复权价格；指标从现金分红生效日起向前连续化，不利用未来分红回改历史 J。农行不套用银行 ETF 拆分。"
        if stock_enabled else
        "处理主仓 2022-09-02 份额合并和银行 ETF 2025-07-07 的 1:2 拆分。银行拆分后数量翻倍、成本参考价与止盈价减半；指标价格按已生效拆分倍数连续化，成交使用原始行情。"
    )
    stock_accounting = (
        "农业银行沿用相邻策略的固定 stock_legacy 股票费用，卖出印花税 0.001、双向过户费 0.00001（可在配置 bank_fees 覆盖），佣金和滑点跟随主仓；实际本次费用详见 metrics.json 的 bank_fees。没有模拟历史税率变更。"
        "分红按相邻策略公告表，仅前一交易日收盘持有的股份在除息日获得现金；卖出交易 PnL 包含所属税前分红，现金只记一次。未扣个人股息税，分红留在现金、不自动追加农行股份。"
        if stock_enabled else "费用由同一 FeeConfig 计算。"
    )
    report = [
        "# 0AMV 必胜策略回测报告", "",
        f"主仓：`{PRIMARY}`；{bank_label}：`{bank_code}`；区间：`{first_date.date()}～{last_date.date()}`；初始资金：{initial_cash:,.0f} 元。", "",
        "> 执行口径：0AMV 信号、动态周线 J 和 ETF 收盘价在收盘后最终确定，本回测沿用“信号日收盘成交”的理想化假设（legacy_same_close_idealized）。", "",
        "## 交易规则", "",
        f"主仓任何规则卖出后开始观察{bank_label}；初始现金阶段不买银行。每日收盘以该标的截至当天的当周周线计算 KDJ(9,3,3)，J<10 时用可用现金全仓买入，整百份/股取整。",
        f"有效主仓进场信号优先：卖出全部{bank_label}后按原规则买回主仓。主仓同日买卖信号冲突仍以离场优先；其余止损、跟踪止盈规则不变。",
        bank_rule, "",
        "## 收益与风险", "", _markdown_metrics(strategy_metrics, benchmark_metrics, original_metrics), "",
        f"策略完成 {strategy_metrics['closed_trade_count']} 笔交易，胜率 {strategy_metrics['win_rate_pct']:.2f}%，资金暴露 {strategy_metrics['exposure_pct']:.2f}%。",
        f"{bank_label}完成 {bank_metrics['closed_trade_count']} 笔交易，已实现盈亏 {bank_metrics['realized_pnl']:,.2f} 元，资金暴露 {bank_metrics['exposure_pct']:.2f}%。",
        f"期末持仓：{json.dumps(open_position, ensure_ascii=False)}。", "",
        "## 年度收益", "", annual.to_markdown(index=False, floatfmt=".2f"), "",
        "## 退出原因", "", json.dumps(exit_counts, ensure_ascii=False, indent=2), "",
        "## 数据与复现", "",
        "周线使用回测起点前的银行历史行情预热，不足 9 周时不触发买入。仅使用截至各观察日的行情；本周后续价格不会影响此前 J 值。",
        corporate_action_rule,
        stock_accounting + " 原纯现金版本和买入持有基准使用相同主仓日期、初始资金与费用。",
        "回测日历沿用原主仓有效交易日；银行缺失必需日期行情会报错。未单独模拟盘口容量、涨跌停无法成交或额外基金现金派息；期末持仓按收盘价估值，不强制卖出。", "",
    ]
    report_text = "\n".join(report)
    report_path.write_text(report_text, encoding="utf-8")
    (output_dir / "report.md").write_text(report_text, encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv-csv", type=Path, default=DEFAULT_AMV_PATH)
    parser.add_argument("--etf-csv", type=Path, default=DEFAULT_ETF_PATH)
    parser.add_argument("--bank-etf-csv", type=Path, default=DEFAULT_BANK_PATH)
    parser.add_argument("--bank-code", choices=(AGRICULTURAL_BANK, BANK), default=AGRICULTURAL_BANK)
    parser.add_argument("--stock-5m-dir", type=Path, default=DEFAULT_STOCK_DATA_DIR)
    parser.add_argument("--stock-dividends-csv", type=Path, default=DEFAULT_STOCK_DIVIDENDS_PATH)
    take_profit = parser.add_mutually_exclusive_group()
    take_profit.add_argument("--bank-take-profit", dest="bank_take_profit", action="store_true",
                             help="银行标的使用 8% 固定价格止盈")
    take_profit.add_argument("--no-bank-take-profit", dest="bank_take_profit", action="store_false",
                             help="银行标的不设固定止盈，仅随主仓进场信号退出")
    parser.set_defaults(bank_take_profit=None)
    parser.add_argument("--start", help="回测开始日期 YYYYMMDD")
    parser.add_argument("--end", help="回测结束日期 YYYYMMDD")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--initial-cash", type=float, default=200_000.0)
    args = parser.parse_args()
    metrics = run_research(
        args.amv_csv, args.etf_csv, args.output_dir, args.report_path, args.initial_cash,
        start_date=args.start, end_date=args.end, bank_path=args.bank_etf_csv,
        bank_take_profit=args.bank_take_profit, bank_code=args.bank_code,
        stock_data_dir=args.stock_5m_dir, stock_dividends_path=args.stock_dividends_csv,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
