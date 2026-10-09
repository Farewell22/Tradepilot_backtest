from __future__ import annotations

import pandas as pd
import pytest

from python.backtest.broker import FeeConfig
from python.strategies.amv_winning_bank_power_defensive.runner import (
    BANK,
    POWER,
    PRIMARY,
    run_defensive_backtest,
)


def _bars(prices: list[float], dates: list[str] | None = None) -> pd.DataFrame:
    sessions = pd.to_datetime(dates) if dates else pd.date_range("2024-01-02", periods=len(prices))
    return pd.DataFrame({
        "date": sessions + pd.Timedelta(hours=15),
        "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": 1_000_000,
    })


def _signals(dates: list[str], *, buys=(), exits=()) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "buy_signal": [index in buys for index in range(len(dates))],
        "exit_ma10": [index in exits for index in range(len(dates))],
        "exit_macd": [False] * len(dates),
    })


def _fees() -> FeeConfig:
    return FeeConfig.etf_legacy().with_overrides(
        commission_rate=0, min_commission=0, slippage_rate=0,
    )


def test_exit_splits_each_cycle_budget_and_buy_rotates_back() -> None:
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    bars = {PRIMARY: _bars([10] * 4), BANK: _bars([5] * 4), POWER: _bars([2] * 4)}
    result = run_defensive_backtest(bars, _signals(dates, buys=(0, 3), exits=(1, 2)),
                                    initial_cash=100_000, fees=_fees())

    assert result.trades[["date", "code", "side"]].values.tolist() == [
        ["20240102", PRIMARY, "buy"],
        ["20240103", PRIMARY, "sell"],
        ["20240103", BANK, "buy"],
        ["20240103", POWER, "buy"],
        ["20240105", BANK, "sell"],
        ["20240105", POWER, "sell"],
        ["20240105", PRIMARY, "buy"],
    ]
    assert result.nav.loc[1, f"{BANK}_quantity"] == 10_000
    assert result.nav.loc[1, f"{POWER}_quantity"] == 25_000
    assert result.nav.loc[2, "nav"] == pytest.approx(100_000)


def test_bank_split_doubles_held_shares_and_preserves_nav() -> None:
    dates = ["2025-07-04", "2025-07-07"]
    bars = {
        PRIMARY: _bars([10, 10], dates),
        BANK: _bars([10, 5], dates),
        POWER: _bars([5, 5], dates),
    }
    result = run_defensive_backtest(bars, _signals(dates, exits=(0,)),
                                    initial_cash=100_000, fees=_fees())

    assert result.nav.loc[0, f"{BANK}_quantity"] == 5_000
    assert result.nav.loc[1, f"{BANK}_quantity"] == 10_000
    assert result.nav.loc[1, "nav"] == pytest.approx(100_000)


def test_primary_intraday_stop_stays_cash_until_amv_exit() -> None:
    dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
    bars = {PRIMARY: _bars([10] * 3), BANK: _bars([5] * 3), POWER: _bars([2] * 3)}
    bars[PRIMARY]["low"] = bars[PRIMARY]["low"].astype(float)
    bars[PRIMARY].loc[1, "low"] = 9.7
    result = run_defensive_backtest(bars, _signals(dates, buys=(0,), exits=(2,)),
                                    initial_cash=100_000, fees=_fees())

    assert result.trades.loc[1, "reason"] == "hard_stop_2.5pct"
    assert result.nav.loc[1, f"{BANK}_quantity"] == 0
    assert result.trades.loc[2:, "code"].tolist() == [BANK, POWER]


def test_defensive_etfs_have_no_inherited_bank_take_profit() -> None:
    dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
    bars = {PRIMARY: _bars([10] * 3), BANK: _bars([5, 5, 6]), POWER: _bars([2, 2, 2.5])}
    result = run_defensive_backtest(bars, _signals(dates, exits=(1, 2)),
                                    initial_cash=100_000, fees=_fees())

    assert result.trades["side"].tolist() == ["buy", "buy"]
    assert result.nav.loc[2, f"{BANK}_quantity"] > 0
    assert result.nav.loc[2, f"{POWER}_quantity"] > 0
