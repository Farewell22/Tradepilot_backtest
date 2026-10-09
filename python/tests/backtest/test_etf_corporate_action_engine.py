import pandas as pd
import pytest

from python.backtest.broker import FeeConfig
from python.backtest import engine


ZERO = FeeConfig.etf_legacy().with_overrides(commission_rate=0, min_commission=0, slippage_rate=0)


def bars(prices):
    rows = []
    for date, opening, closing in prices:
        rows.append(dict(timestamp=f"{date} 09:30", code="ETF", open=opening, high=opening, low=opening, close=opening))
        rows.append(dict(timestamp=f"{date} 15:00", code="ETF", open=closing, high=closing, low=closing, close=closing))
    return pd.DataFrame(rows)


class Nothing:
    def on_bar(self, context):
        return []


def initial():
    return [(pd.Timestamp("2024-01-01 15:00"), engine.CashBuyIntent("ETF"))]


def dividend(record="2024-01-02", ex="2024-01-03", pay="2024-01-04", amount=1):
    from python.backtest.corporate_actions import CorporateAction
    return CorporateAction("ETF", "dividend", pd.Timestamp(record), pd.Timestamp(ex), pd.Timestamp(pay), cash_per_share=amount)


def test_cash_sizing_uses_next_open_and_commission():
    fee = ZERO.with_overrides(min_commission=5)
    result = engine.Engine(fee).run(bars([("2024-01-02", 12, 12)]), Nothing(), 1000, initial_orders=initial())
    assert result.positions == []  # 100 shares cost 1205; never spend unavailable cash.
    result = engine.Engine(fee).run(bars([("2024-01-02", 3, 3)]), Nothing(), 1000, initial_orders=initial())
    assert result.positions[0].buy_quantity == 300
    assert result.cash == 95
    assert result.fills[0]["time"] == "09:30:00"


def test_dividend_claim_survives_sale_and_is_paid_once():
    class Sell:
        def on_bar(self, context):
            return [engine.SellAllIntent("ETF")] if context.timestamp == pd.Timestamp("2024-01-02 15:00") else []
    result = engine.Engine(ZERO).run(bars([("2024-01-02", 10, 10), ("2024-01-03", 9, 9), ("2024-01-04", 9, 9)]), Sell(), 1000, initial_orders=initial(), corporate_actions=[dividend()])
    assert result.nav_history == [("20240102", 1000), ("20240103", 1000), ("20240104", 1000)]
    assert result.cash == 1000
    assert result.dividend_receivable == 0
    assert result.closed_trades[0].pnl == 0
    assert result.closed_trades[0].dividend_income == 100
    assert sum(x["amount"] for x in result.corporate_action_ledger if x["action"] == "paid") == 100


def test_payment_reinvestment_occurs_at_following_open_and_context_sums_lots():
    seen = []
    class Reinvest:
        def on_bar(self, context):
            if context.timestamp.hour == 15:
                seen.append(context.positions["ETF"].quantity)
            return [engine.CashBuyIntent("ETF", reason="dividend_reinvestment")] if context.dividend_cash.get("ETF", 0) else []
    result = engine.Engine(ZERO).run(bars([("2024-01-02", 10, 10), ("2024-01-03", 5, 5), ("2024-01-04", 5, 5), ("2024-01-05", 5, 5)]), Reinvest(), 1000, initial_orders=initial(), corporate_actions=[dividend(amount=5)])
    assert [fill["date"] for fill in result.fills] == ["20240102", "20240105"]
    assert seen == [100, 100, 100, 200]
    assert result.total_value == 1000


def test_buying_on_ex_date_does_not_receive_previous_dividend():
    order = [(pd.Timestamp("2024-01-02 15:00"), engine.CashBuyIntent("ETF"))]
    result = engine.Engine(ZERO).run(bars([("2024-01-03", 9, 9), ("2024-01-04", 9, 9)]), Nothing(), 1000, initial_orders=order, corporate_actions=[dividend()])
    assert result.corporate_action_ledger == []
    assert result.cash == 100


def test_split_before_queued_liquidation_preserves_value_and_cost():
    from python.backtest.corporate_actions import CorporateAction
    action = CorporateAction("ETF", "split", pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"), split_ratio=2)
    class Sell:
        def on_bar(self, context):
            return [engine.SellAllIntent("ETF")] if context.timestamp.hour == 15 else []
    result = engine.Engine(ZERO).run(bars([("2024-01-02", 10, 10), ("2024-01-03", 5, 5)]), Sell(), 1000, initial_orders=initial(), corporate_actions=[action])
    assert result.cash == 1000
    assert result.positions == []
    assert result.closed_trades[0].buy_quantity == 200
    assert result.closed_trades[0].buy_cost == 1000
    assert result.closed_trades[0].pnl == 0


def test_t1_defers_same_day_sell_to_next_open():
    class SellImmediately:
        def on_bar(self, context):
            return [engine.SellAllIntent("ETF")] if context.timestamp == pd.Timestamp("2024-01-02 09:30") else []
    result = engine.Engine(ZERO).run(bars([("2024-01-02", 10, 10), ("2024-01-03", 11, 11)]), SellImmediately(), 1000, initial_orders=initial(), enforce_t1=True)
    assert result.closed_trades[0].sell_date == "20240103"
    assert result.closed_trades[0].sell_time == "09:30:00"
    assert result.cash == 1100


def test_last_day_receivable_is_part_of_nav_before_cash_payment():
    result = engine.Engine(ZERO).run(bars([("2024-01-02", 10, 10), ("2024-01-03", 9, 9)]), Nothing(), 1000, initial_orders=initial(), corporate_actions=[dividend()])
    assert result.cash == 0
    assert result.dividend_receivable == 100
    assert result.total_value == 1000
