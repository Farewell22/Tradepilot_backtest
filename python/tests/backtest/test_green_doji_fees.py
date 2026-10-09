from python.backtest.broker import FeeConfig
from python.strategies.green_doji.strategy import calc_buy_cost, calc_sell_proceeds
from python.strategies.green_doji import strategy
import pytest


def test_green_doji_costs_accept_per_run_fees():
    fees = FeeConfig(commission_rate=0, min_commission=0, stamp_duty_rate=0,
                     transfer_fee_rate=0, slippage_rate=0)
    assert calc_buy_cost(10, 100, fees) == (10, 1000)
    assert calc_sell_proceeds(10, 100, fees) == (10, 1000)


def test_green_doji_rejects_requested_period_without_trading_data(tmp_path, monkeypatch):
    monkeypatch.setattr(strategy, "scan_trading_days", lambda start, end: [])
    with pytest.raises(ValueError, match="无可用交易日"):
        strategy.run_backtest(start_date="20300101", end_date="20300131", output_dir=str(tmp_path))
