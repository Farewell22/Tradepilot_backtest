"""Close-known regime decisions and cash dividend reinvestment."""
from __future__ import annotations

import pandas as pd

from python.backtest.engine import CashBuyIntent, SellAllIntent, StrategyContext


class AmvBelowMaStrategy:
    def __init__(self, code: str, period: int | None, signals: pd.DataFrame):
        self.code = code
        self.period = period
        self.signals = signals.set_index("date")
        self.episode_id = ""

    def eligible(self, date: pd.Timestamp) -> bool:
        return self.period is None or bool(self.signals.at[date, f"below_ma{self.period}"])

    def entry(self, date: pd.Timestamp) -> CashBuyIntent:
        mode = f"ma{self.period}" if self.period else "buy_hold"
        self.episode_id = f"{self.code}_{mode}_{date:%Y%m%d}"
        return CashBuyIntent(self.code, episode_id=self.episode_id)

    def on_bar(self, context: StrategyContext):
        if context.timestamp.hour != 15:
            return []
        date = context.timestamp.normalize()
        held = self.code in context.positions
        if not self.eligible(date):
            return [SellAllIntent(self.code, reason="amv_recovered", episode_id=self.episode_id)] if held else []
        if not held:
            return [self.entry(date)]
        if context.dividend_cash.get(self.code, 0) > 0:
            return [CashBuyIntent(self.code, reason="dividend_reinvestment", episode_id=self.episode_id)]
        return []
