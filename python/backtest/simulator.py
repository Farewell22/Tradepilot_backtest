"""Compatibility exports for the former simulator module.

Strategy selection and stop rules live in ``python.strategies``.
"""
from __future__ import annotations

from python.backtest.broker import FeeConfig
from python.backtest.broker import calc_buy_cost as _calc_buy_cost
from python.backtest.broker import calc_sell_proceeds as _calc_sell_proceeds
from python.backtest.models import Portfolio, Trade

COMMISSION_RATE = 0.0003
STAMP_DUTY_RATE = 0.001
TRANSFER_FEE_RATE = 0.00001
SLIPPAGE_RATE = 0.001


def calc_buy_cost(price: float, quantity: int, fees: FeeConfig | None = None) -> tuple[float, float]:
    return _calc_buy_cost(price, quantity, fees or FeeConfig.stock_legacy())


def calc_sell_proceeds(price: float, quantity: int, fees: FeeConfig | None = None) -> tuple[float, float]:
    return _calc_sell_proceeds(price, quantity, fees or FeeConfig.stock_legacy())
