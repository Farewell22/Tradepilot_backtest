"""Event-based backtest engine with next-available-bar execution."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal, Mapping, Protocol

import pandas as pd
import numpy as np

from python.backtest.broker import FeeConfig, calc_buy_cost, calc_sell_proceeds
from python.backtest.models import Portfolio, Trade
from python.backtest.corporate_actions import CorporateAction, CorporateActionBook


@dataclass(frozen=True)
class OrderIntent:
    code: str
    side: Literal["buy", "sell"]
    quantity: int

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell") or self.quantity <= 0 or not self.code:
            raise ValueError("order requires a code, buy/sell side, and positive quantity")


@dataclass(frozen=True)
class CashBuyIntent:
    code: str
    lot_size: int = 100
    reason: str = "entry"
    episode_id: str = ""

    def __post_init__(self):
        if not self.code or not isinstance(self.lot_size, int) or self.lot_size <= 0:
            raise ValueError("cash buy requires a code and positive integer lot size")


@dataclass(frozen=True)
class SellAllIntent:
    code: str
    reason: str = "exit"
    episode_id: str = ""

    def __post_init__(self):
        if not self.code:
            raise ValueError("liquidation requires a code")


Intent = OrderIntent | CashBuyIntent | SellAllIntent


@dataclass(frozen=True)
class Bar:
    timestamp: pd.Timestamp
    code: str
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class PositionView:
    quantity: int
    last_close: float


@dataclass(frozen=True)
class StrategyContext:
    timestamp: pd.Timestamp
    bars: Mapping[str, Bar]
    cash: float
    positions: Mapping[str, PositionView]
    dividend_cash: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))


class Strategy(Protocol):
    def on_bar(self, context: StrategyContext) -> list[Intent]: ...


class Engine:
    def __init__(self, fees: FeeConfig | None = None) -> None:
        self.fees = fees or FeeConfig.stock_legacy()

    def run(self, bars: pd.DataFrame, strategy: Strategy, initial_cash: float, *,
            initial_orders: list[tuple[pd.Timestamp, Intent]] | None = None,
            corporate_actions: list[CorporateAction] | None = None,
            enforce_t1: bool = False) -> Portfolio:
        required = {"timestamp", "code", "open", "high", "low", "close"}
        missing = required.difference(bars.columns)
        if missing:
            raise ValueError(f"bars missing columns: {', '.join(sorted(missing))}")
        if not np.isfinite(initial_cash) or initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        source = bars.loc[:, ["timestamp", "code", "open", "high", "low", "close"]].copy()
        source["timestamp"] = pd.to_datetime(source["timestamp"], errors="raise")
        source = source.sort_values(["timestamp", "code"])
        if source.duplicated(["timestamp", "code"]).any():
            raise ValueError("duplicate timestamp and code")
        if not np.isfinite(source[["open", "high", "low", "close"]].to_numpy(dtype=float)).all() or (source[["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError("bar prices must be positive")

        portfolio = Portfolio(initial_cash=initial_cash, cash=initial_cash)
        pending = [(pd.Timestamp(timestamp), intent) for timestamp, intent in (initial_orders or [])]
        if pending and (source.empty or any(timestamp >= source.timestamp.min() for timestamp, _ in pending)):
            raise ValueError("initial orders must precede the first bar")
        book = CorporateActionBook(portfolio, corporate_actions or [])
        last_times = source.groupby(source.timestamp.dt.normalize()).timestamp.max().to_dict()
        previous_day = None
        for timestamp, rows in source.groupby("timestamp", sort=True):
            date = timestamp.normalize()
            if previous_day != date:
                book.on_open(date)
            previous_day = date
            current = {
                str(row.code): Bar(timestamp, str(row.code), float(row.open), float(row.high), float(row.low), float(row.close))
                for row in rows.itertuples(index=False)
            }
            waiting = []
            for signal_time, intent in pending:
                bar = current.get(intent.code)
                if bar is None or timestamp <= signal_time:
                    waiting.append((signal_time, intent))
                    continue
                remainder = self._fill(portfolio, intent, bar, signal_time, enforce_t1)
                if remainder is not None:
                    waiting.append((signal_time, remainder))
            pending = waiting

            for position in portfolio.positions:
                bar = current.get(position.code)
                if bar is not None:
                    position.last_close = bar.close
            payments = book.on_close(date) if timestamp == last_times[date] else {}
            day = timestamp.strftime("%Y%m%d")
            if portfolio.nav_history and portfolio.nav_history[-1][0] == day:
                portfolio.nav_history[-1] = (day, portfolio.total_value)
            else:
                portfolio.nav_history.append((day, portfolio.total_value))

            views: dict[str, PositionView] = {}
            for position in portfolio.positions:
                quantity = views[position.code].quantity if position.code in views else 0
                views[position.code] = PositionView(quantity + position.buy_quantity, position.last_close)
            if timestamp == last_times[date]:
                portfolio.daily_snapshots.append({"date": day, "nav": portfolio.total_value,
                    "cash": portfolio.cash, "dividend_receivable": portfolio.dividend_receivable,
                    "dividend_income": portfolio.dividend_income_total,
                    "invested": bool(views), "quantity": sum(view.quantity for view in views.values())})

            context = StrategyContext(
                timestamp=timestamp,
                bars=MappingProxyType(current),
                cash=portfolio.cash,
                positions=MappingProxyType(views),
                dividend_cash=MappingProxyType(payments),
            )
            pending.extend((timestamp, intent) for intent in strategy.on_bar(context))
        return portfolio

    def _fill(self, portfolio: Portfolio, intent: Intent, bar: Bar,
              signal_time: pd.Timestamp, enforce_t1: bool) -> Intent | None:
        day = bar.timestamp.strftime("%Y%m%d")
        clock = bar.timestamp.strftime("%H:%M:%S")
        nav_before = portfolio.cash + portfolio.dividend_receivable + sum(
            position.buy_quantity * (bar.open if position.code == bar.code else position.last_close)
            for position in portfolio.positions)
        if isinstance(intent, CashBuyIntent) or isinstance(intent, OrderIntent) and intent.side == "buy":
            if isinstance(intent, CashBuyIntent):
                quantity = int(portfolio.cash / (bar.open * (1 + self.fees.slippage_rate))) // intent.lot_size * intent.lot_size
                while quantity > 0 and calc_buy_cost(bar.open, quantity, self.fees)[1] > portfolio.cash:
                    quantity -= intent.lot_size
            else:
                quantity = intent.quantity
            if quantity <= 0:
                return None
            execution, cost = calc_buy_cost(bar.open, quantity, self.fees)
            if cost > portfolio.cash:
                return None
            portfolio.cash -= cost
            portfolio.positions.append(Trade(
                code=intent.code, buy_date=day, buy_time=clock,
                buy_signal_price=bar.open, buy_exec_price=execution,
                buy_quantity=quantity, buy_cost=cost, last_close=bar.close,
                holding_id=len([fill for fill in portfolio.fills if fill["side"] == "buy"]) + 1,
                episode_id=getattr(intent, "episode_id", ""),
            ))
            portfolio.fills.append({"date": day, "time": clock, "code": bar.code, "side": "buy",
                "quantity": quantity, "signal_date": signal_time.strftime("%Y%m%d"),
                "signal_time": signal_time.strftime("%H:%M:%S"), "signal_price": bar.open,
                "exec_price": execution, "cash_flow": -cost, "fees": cost - execution * quantity,
                "slippage_cost": (execution - bar.open) * quantity, "nav_before": nav_before,
                "nav_after": nav_before - cost + quantity * bar.open,
                "reason": getattr(intent, "reason", "entry"), "episode_id": getattr(intent, "episode_id", "")})
            return None

        available = [position for position in portfolio.positions if position.code == intent.code
                     and (not enforce_t1 or position.buy_date < day)]
        if isinstance(intent, SellAllIntent):
            quantity = sum(position.buy_quantity for position in available)
            if quantity > 0:
                execution, proceeds = calc_sell_proceeds(bar.open, quantity, self.fees)
                for position in available:
                    self._close_lot(portfolio, position, position.buy_quantity, execution,
                                    proceeds * position.buy_quantity / quantity, day, clock, bar.open, intent.reason)
                portfolio.cash += proceeds
                portfolio.fills.append({"date": day, "time": clock, "code": bar.code, "side": "sell",
                    "quantity": quantity, "signal_date": signal_time.strftime("%Y%m%d"),
                    "signal_time": signal_time.strftime("%H:%M:%S"), "signal_price": bar.open,
                    "exec_price": execution, "cash_flow": proceeds, "fees": execution * quantity - proceeds,
                    "slippage_cost": (bar.open - execution) * quantity, "nav_before": nav_before,
                    "nav_after": nav_before + proceeds - quantity * bar.open,
                    "reason": intent.reason, "episode_id": intent.episode_id})
            return intent if any(position.code == intent.code for position in portfolio.positions) else None

        remaining = intent.quantity
        for position in list(portfolio.positions):
            if position not in available or remaining <= 0:
                continue
            sold = min(position.buy_quantity, remaining)
            execution, proceeds = calc_sell_proceeds(bar.open, sold, self.fees)
            self._close_lot(portfolio, position, sold, execution, proceeds, day, clock, bar.open, "strategy_sell")
            portfolio.cash += proceeds
            remaining -= sold
        return replace(intent, quantity=remaining) if enforce_t1 and remaining > 0 and any(position.code == intent.code for position in portfolio.positions) else None

    @staticmethod
    def _close_lot(portfolio, position, sold, execution, proceeds, day, clock, price, reason):
        fraction = sold / position.buy_quantity
        cost_basis = position.buy_cost * fraction
        income = position.dividend_income * fraction
        closed = replace(position, buy_quantity=sold, buy_cost=cost_basis, dividend_income=income,
                         sell_date=day, sell_time=clock, sell_signal_price=price,
                         sell_exec_price=execution, sell_proceeds=proceeds, sell_reason=reason)
        closed.pnl = proceeds + income - cost_basis
        closed.pnl_pct = closed.pnl / cost_basis * 100 if cost_basis else 0.0
        closed.hold_days = (pd.Timestamp(day) - pd.Timestamp(position.buy_date)).days
        portfolio.closed_trades.append(closed)
        position.buy_quantity -= sold
        position.buy_cost -= cost_basis
        position.dividend_income -= income
        if position.buy_quantity == 0:
            portfolio.positions.remove(position)
