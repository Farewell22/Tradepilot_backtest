"""Shared trade and portfolio records for backtest results."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Trade:
    code: str
    buy_date: str
    buy_time: str
    buy_signal_price: float
    buy_exec_price: float
    buy_quantity: int
    buy_cost: float
    buy_signal_type: str = ""
    buy_day_low: float = 0.0
    last_day_low: float = 0.0
    last_day_open: float = 0.0
    prev_day_break_count: int = 0
    days_held: int = 0
    last_close: float = 0.0
    highest_price: float = 0.0
    sell_date: str = ""
    sell_time: str = ""
    sell_signal_price: float = 0.0
    sell_exec_price: float = 0.0
    sell_proceeds: float = 0.0
    sell_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    hold_days: int = 0
    score: float = 0.0
    bear_trade: bool = False
    holding_id: int = 0
    episode_id: str = ""
    dividend_income: float = 0.0


@dataclass
class Portfolio:
    initial_cash: float
    cash: float
    max_positions: int = 4
    positions: list[Trade] = field(default_factory=list)
    closed_trades: list[Trade] = field(default_factory=list)
    nav_history: list[tuple[str, float]] = field(default_factory=list)
    dividend_receivable: float = 0.0
    dividend_income_total: float = 0.0
    fills: list[dict] = field(default_factory=list)
    daily_snapshots: list[dict] = field(default_factory=list)
    corporate_action_ledger: list[dict] = field(default_factory=list)

    @property
    def total_value(self) -> float:
        """Cash plus positions marked at the last available close."""
        return self.cash + self.dividend_receivable + sum(position.buy_quantity * position.last_close for position in self.positions)
