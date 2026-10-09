"""Per-run transaction cost model shared by backtests."""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class FeeConfig:
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    stamp_duty_rate: float = 0.001
    transfer_fee_rate: float = 0.00001
    slippage_rate: float = 0.001

    def __post_init__(self) -> None:
        for name in (
            "commission_rate", "min_commission", "stamp_duty_rate",
            "transfer_fee_rate", "slippage_rate",
        ):
            value = getattr(self, name)
            if not 0 <= value < float("inf"):
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.slippage_rate >= 1:
            raise ValueError("slippage_rate must be below 1")

    @classmethod
    def stock_legacy(cls) -> FeeConfig:
        return cls()

    @classmethod
    def etf_legacy(cls) -> FeeConfig:
        return cls(stamp_duty_rate=0.0, transfer_fee_rate=0.0)

    def with_overrides(self, **values: float) -> FeeConfig:
        return replace(self, **values)


def calc_buy_cost(price: float, quantity: int, fees: FeeConfig) -> tuple[float, float]:
    if price <= 0 or quantity <= 0:
        raise ValueError("price and quantity must be positive")
    exec_price = price * (1 + fees.slippage_rate)
    gross = exec_price * quantity
    commission = max(fees.min_commission, gross * fees.commission_rate)
    return exec_price, gross + commission + gross * fees.transfer_fee_rate


def calc_sell_proceeds(price: float, quantity: int, fees: FeeConfig) -> tuple[float, float]:
    if price <= 0 or quantity <= 0:
        raise ValueError("price and quantity must be positive")
    exec_price = price * (1 - fees.slippage_rate)
    gross = exec_price * quantity
    commission = max(fees.min_commission, gross * fees.commission_rate)
    stamp_duty = gross * fees.stamp_duty_rate
    transfer_fee = gross * fees.transfer_fee_rate
    return exec_price, gross - commission - stamp_duty - transfer_fee
