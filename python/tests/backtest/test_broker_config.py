import pytest

from python.backtest.broker import FeeConfig, calc_buy_cost, calc_sell_proceeds
from python.backtest.simulator import calc_buy_cost as legacy_buy_cost


def test_stock_default_costs_match_legacy_behavior():
    fees = FeeConfig.stock_legacy()
    assert calc_buy_cost(10.0, 100, fees) == pytest.approx((10.01, 1006.01001))
    assert calc_sell_proceeds(10.0, 100, fees) == pytest.approx((9.99, 992.99101))


def test_stock_sell_preserves_legacy_floating_operation_order():
    # The historical simulator subtracts stamp duty and transfer fee separately.
    assert calc_sell_proceeds(3.6, 55_800, FeeConfig.stock_legacy())[1] == 200416.23035280002


def test_etf_profile_omits_stamp_and_transfer_and_override_is_isolated():
    default = FeeConfig.etf_legacy()
    custom = FeeConfig.etf_legacy().with_overrides(slippage_rate=0.0, commission_rate=0.0, min_commission=0.0)
    assert calc_sell_proceeds(10.0, 100, default) == pytest.approx((9.99, 994.0))
    assert calc_sell_proceeds(10.0, 100, custom) == pytest.approx((10.0, 1000.0))
    assert calc_sell_proceeds(10.0, 100, default) == pytest.approx((9.99, 994.0))


def test_negative_fee_rate_is_rejected():
    with pytest.raises(ValueError, match="slippage_rate"):
        FeeConfig(slippage_rate=-0.01)


def test_slippage_cannot_make_sell_execution_price_nonpositive():
    with pytest.raises(ValueError, match="slippage_rate"):
        FeeConfig(slippage_rate=1.0)


def test_legacy_simulator_can_use_per_run_fees():
    waived = FeeConfig.stock_legacy().with_overrides(
        commission_rate=0.0, min_commission=0.0,
        stamp_duty_rate=0.0, transfer_fee_rate=0.0, slippage_rate=0.0,
    )
    assert legacy_buy_cost(10.0, 100, waived) == (10.0, 1000.0)
    assert legacy_buy_cost(10.0, 100) == pytest.approx((10.01, 1006.01001))
