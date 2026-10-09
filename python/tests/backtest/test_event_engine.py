import pandas as pd

from python.backtest.broker import FeeConfig
from python.backtest.engine import Engine, OrderIntent


class BuyFirstBar:
    def on_bar(self, context):
        if context.timestamp == pd.Timestamp("2024-01-02 15:00:00"):
            return [OrderIntent(code="510300", side="buy", quantity=100)]
        return []


def test_close_signal_fills_at_next_bar_open():
    bars = pd.DataFrame([
        {"timestamp": "2024-01-02 15:00:00", "code": "510300", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0},
        {"timestamp": "2024-01-03 09:30:00", "code": "510300", "open": 12.0, "high": 13.0, "low": 12.0, "close": 13.0},
    ])
    zero_fees = FeeConfig.etf_legacy().with_overrides(
        commission_rate=0.0, min_commission=0.0, slippage_rate=0.0,
    )
    portfolio = Engine(fees=zero_fees).run(bars, BuyFirstBar(), initial_cash=10_000.0)
    assert portfolio.positions[0].buy_exec_price == 12.0
    assert portfolio.positions[0].buy_date == "20240103"
    assert portfolio.nav_history == [("20240102", 10_000.0), ("20240103", 10_100.0)]
