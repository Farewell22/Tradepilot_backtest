"""Daily 510300 ETF strategy driven by classified 0AMV signals."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from python.backtest.broker import FeeConfig
from python.backtest.market_data import normalize_etf_history, normalize_etf_intraday
from python.factors.amv_signals import align_amv_sell_signals
from python.backtest.simulator import SLIPPAGE_RATE, Trade, calc_buy_cost, calc_sell_proceeds


SIGNAL_PRIORITY = {"worst": 1, "secondary": 2, "best": 3}
TARGET_WEIGHTS = {"worst": 0.25, "secondary": 0.50, "best": 1.00}
STOP_LOSS = {"worst": 0.05, "secondary": 0.05, "best": 0.05}
MAX_HOLD_DAYS = {"worst": 10, "secondary": 30, "best": 40}
PROFIT_TRAIL_THRESHOLD = {"best": 0.08, "secondary": 0.08, "worst": 0.05}


class AmvSignalDetector:
    """Classify trend signals with a five-session momentum confirmation window."""

    def detect(self, amv: pd.DataFrame, momentum_window_days: int = 5) -> pd.DataFrame:
        required = {"date", "close"}
        missing = required.difference(amv.columns)
        if missing:
            raise ValueError(f"0AMV 数据缺少列: {', '.join(sorted(missing))}")
        if int(momentum_window_days) <= 0:
            raise ValueError("动量确认窗口必须为正整数")
        result = amv.loc[:, ["date", "close"]].copy()
        result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
        result["close"] = pd.to_numeric(result["close"], errors="raise")
        if result["date"].duplicated().any() or (result["close"] <= 0).any():
            raise ValueError("0AMV 数据存在重复日期或非正收盘价")
        result = result.sort_values("date").reset_index(drop=True)
        result["ma10"] = result["close"].rolling(10).mean()
        result["ma20"] = result["close"].rolling(20).mean()
        result["ma60"] = result["close"].rolling(60).mean()
        result["momentum_3"] = result["close"].pct_change(3)
        cross_ma10 = (result["close"] > result["ma10"]) & (
            result["close"].shift(1) <= result["ma10"].shift(1)
        )
        cross_ma20 = (result["close"] > result["ma20"]) & (
            result["close"].shift(1) <= result["ma20"].shift(1)
        )
        momentum_confirmed = (result["momentum_3"] > 0.04) & (result["close"] > result["ma60"])
        candidates: list[tuple[int, str]] = []
        for index in result.index[cross_ma20]:
            hits = result.index[index:index + int(momentum_window_days)][momentum_confirmed.iloc[index:index + int(momentum_window_days)]]
            if len(hits):
                candidates.append((int(hits[0]), "best"))
        for index in result.index[cross_ma10 & ~cross_ma20]:
            hits = result.index[index:index + int(momentum_window_days)][momentum_confirmed.iloc[index:index + int(momentum_window_days)]]
            if len(hits):
                candidates.append((int(hits[0]), "secondary"))

        # If overlapping windows resolve to the same execution day, keep the stronger signal.
        signal_priority = {"secondary": 1, "best": 2}
        selected: dict[int, str] = {}
        for index, signal_type in candidates:
            if signal_priority[signal_type] > signal_priority.get(selected.get(index, ""), 0):
                selected[index] = signal_type
        for index, signal_type in selected.items():
            result.loc[index, "signal_type"] = signal_type
        # Retain the historical worst signal as a diagnostic/optional low-weight signal.
        worst = result["signal_type"].isna() & (result["close"] > result["ma20"]) & (result["momentum_3"] > 0.03) & (result["close"] > result["ma60"])
        result.loc[worst, "signal_type"] = "worst"
        return result.loc[result["signal_type"].notna(), ["date", "close", "momentum_3", "signal_type"]].reset_index(drop=True)


@dataclass
class EtfPosition:
    trade: Trade
    entry_day_index: int
    signal_type: str
    quantity: int
    avg_buy_exec_price: float
    profit_armed: bool = False
    take_profit_price: float | None = None


class EtfPortfolio:
    def __init__(
        self,
        initial_cash: float,
        target_weights: dict[str, float] | None = None,
        stop_loss: dict[str, float] | None = None,
        max_hold_days: int | dict[str, int] = 10,
        profit_trail_threshold: float | dict[str, float] = PROFIT_TRAIL_THRESHOLD,
        fees: FeeConfig | None = None,
    ):
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.fees = fees or FeeConfig.stock_legacy()
        self.target_weights = target_weights or deepcopy(TARGET_WEIGHTS)
        self.stop_loss = stop_loss or deepcopy(STOP_LOSS)
        self.max_hold_days = (deepcopy(max_hold_days) if isinstance(max_hold_days, dict)
                              else {signal: int(max_hold_days) for signal in SIGNAL_PRIORITY})
        self.profit_trail_threshold = (
            deepcopy(profit_trail_threshold)
            if isinstance(profit_trail_threshold, dict)
            else {signal: float(profit_trail_threshold) for signal in SIGNAL_PRIORITY}
        )
        self.position: EtfPosition | None = None
        self.closed_trades: list[Trade] = []
        self.nav_history: list[tuple[str, float]] = []

    def apply_signal(self, date: str, day_index: int, signal_type: str, open_price: float) -> EtfPosition | None:
        if signal_type not in SIGNAL_PRIORITY:
            raise ValueError(f"未知信号类型: {signal_type}")
        if open_price <= 0:
            return None
        if self.position is not None and SIGNAL_PRIORITY[signal_type] <= SIGNAL_PRIORITY[self.position.signal_type]:
            return self.position

        target_value = self.initial_cash * self.target_weights[signal_type]
        exec_price = open_price * (1 + self.fees.slippage_rate)
        current_value = self.position.quantity * exec_price if self.position is not None else 0.0
        additional = int(max(0.0, target_value - current_value) / exec_price) // 100 * 100
        while additional > 0:
            _, cost = calc_buy_cost(open_price, additional, self.fees)
            if cost <= self.cash:
                break
            additional -= 100
        if additional <= 0:
            if self.position is not None:
                self.position.signal_type = signal_type
            return self.position

        if self.position is None:
            trade = Trade(
                code="510300.SH", buy_date=date, buy_time="open", buy_signal_price=open_price,
                buy_exec_price=exec_price, buy_quantity=additional, buy_cost=cost,
                buy_signal_type=signal_type, last_close=open_price,
            )
            self.position = EtfPosition(trade, day_index, signal_type, additional, exec_price)
        else:
            position = self.position
            total_quantity = position.quantity + additional
            position.avg_buy_exec_price = (
                position.avg_buy_exec_price * position.quantity + exec_price * additional
            ) / total_quantity
            position.quantity = total_quantity
            position.signal_type = signal_type
            position.trade.buy_quantity = total_quantity
            position.trade.buy_cost += cost
            position.trade.buy_exec_price = position.avg_buy_exec_price
        self.cash -= cost
        return self.position

    def update_daily_take_profit(self, previous_body_low: float, previous_close: float) -> None:
        """After +8% profit, trail the previous daily candle body low."""
        if self.position is None or previous_body_low <= 0 or previous_close <= 0:
            return
        profit_threshold = self.position.avg_buy_exec_price * (1 + self.profit_trail_threshold[self.position.signal_type])
        if self.position.profit_armed:
            self.position.take_profit_price = float(previous_body_low)

    def force_sell(self, date: str, day_index: int, open_price: float, reason: str) -> Trade | None:
        """Close the complete position at the session open for a signal exit."""
        if self.position is None or open_price <= 0:
            return None
        position = self.position
        trade = position.trade
        exec_price, proceeds = calc_sell_proceeds(float(open_price), position.quantity, self.fees)
        trade.sell_date = date.replace("-", "")
        trade.sell_time = "open"
        trade.sell_signal_price = float(open_price)
        trade.sell_exec_price = exec_price
        trade.sell_proceeds = proceeds
        trade.sell_reason = reason
        trade.pnl = proceeds - trade.buy_cost
        trade.pnl_pct = trade.pnl / trade.buy_cost * 100 if trade.buy_cost else 0.0
        trade.hold_days = day_index - position.entry_day_index
        self.cash += proceeds
        self.closed_trades.append(trade)
        self.position = None
        return trade

    def process_intraday_bar(
        self,
        date: str,
        day_index: int,
        bar: dict[str, float],
        previous_bar: dict[str, float] | None,
    ) -> Trade | None:
        position = self.position
        if position is None:
            return None
        trade = position.trade
        trade.last_close = float(bar["close"])
        if day_index == position.entry_day_index:
            if float(bar["high"]) >= position.avg_buy_exec_price * (1 + self.profit_trail_threshold[position.signal_type]):
                position.profit_armed = True
            return None
        stop_pct = self.stop_loss[position.signal_type]
        stop = position.avg_buy_exec_price * (1 - stop_pct)
        open_price = float(bar["open"])
        sell_price = None
        reason = None
        if float(bar["low"]) <= stop:
            sell_price = min(open_price, stop)
            reason = f"stop_loss_{position.signal_type}_{stop_pct * 100:g}pct"
        else:
            if float(bar["high"]) >= position.avg_buy_exec_price * (1 + self.profit_trail_threshold[position.signal_type]):
                position.profit_armed = True
            take_profit = position.take_profit_price
            if take_profit is not None and float(bar["low"]) < take_profit:
                sell_price = min(open_price, take_profit)
                reason = f"profit_trail_body_break_{position.signal_type}"
        if sell_price is not None:
            exec_price, proceeds = calc_sell_proceeds(sell_price, position.quantity, self.fees)
            trade.sell_date = date.split()[0].replace("-", "")
            trade.sell_time = date.split()[1] if " " in date else "intraday"
            trade.sell_signal_price = sell_price
            trade.sell_exec_price = exec_price
            trade.sell_proceeds = proceeds
            trade.sell_reason = reason
            trade.pnl = proceeds - trade.buy_cost
            trade.pnl_pct = trade.pnl / trade.buy_cost * 100 if trade.buy_cost else 0.0
            trade.hold_days = day_index - position.entry_day_index
            self.cash += proceeds
            self.closed_trades.append(trade)
            self.position = None
        return trade if sell_price is not None else None

    def process_day_close(self, date: str, day_index: int, close_price: float) -> Trade | None:
        """Record NAV and enforce the signal-specific maximum holding period."""
        position = self.position
        if position is not None and day_index - position.entry_day_index >= self.max_hold_days[position.signal_type]:
            trade = position.trade
            exec_price, proceeds = calc_sell_proceeds(float(close_price), position.quantity, self.fees)
            trade.sell_date = date.replace("-", "")
            trade.sell_time = "close"
            trade.sell_signal_price = float(close_price)
            trade.sell_exec_price = exec_price
            trade.sell_proceeds = proceeds
            trade.sell_reason = f"time_exit_t{self.max_hold_days[position.signal_type]}_{position.signal_type}"
            trade.pnl = proceeds - trade.buy_cost
            trade.pnl_pct = trade.pnl / trade.buy_cost * 100 if trade.buy_cost else 0.0
            trade.hold_days = day_index - position.entry_day_index
            self.cash += proceeds
            self.closed_trades.append(trade)
            self.position = None
        self.nav_history.append((date.replace("-", ""), self.total_value(float(close_price))))
        return trade if position is not None and self.position is None else None

    def process_day(self, date: str, day_index: int, bar: dict[str, float]) -> Trade | None:
        """Compatibility helper for callers that only have daily bars."""
        closed = self.process_intraday_bar(date, day_index, bar, None)
        if closed is not None:
            self.nav_history.append((date, self.total_value(float(bar["close"]))))
            return closed
        return self.process_day_close(date, day_index, float(bar["close"]))

    def total_value(self, last_close: float | None = None) -> float:
        if self.position is None:
            return self.cash
        price = last_close if last_close is not None else self.position.trade.last_close
        return self.cash + self.position.quantity * price
