from __future__ import annotations

import pandas as pd
import pytest

from python.backtest.broker import FeeConfig
from python.strategies.amv_winning_defensive_5d.runner import run_variant


def bars(closes: list[float], start: str = "2024-05-06") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({
        "date": dates + pd.Timedelta(hours=15), "open": closes, "high": closes,
        "low": closes, "close": closes, "volume": 1_000_000,
    })


def signals(count: int, death_at: int, momentum: float, buy_at: int | None = None) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.bdate_range("2024-05-06", periods=count),
        "buy_signal": [i == buy_at for i in range(count)],
        "exit_macd": [i == death_at for i in range(count)],
        "exit_ma10": [False] * count,
        "momentum_3": [momentum] * count,
    })


def no_fees() -> FeeConfig:
    return FeeConfig.etf_legacy().with_overrides(commission_rate=0, min_commission=0, slippage_rate=0)


def test_severe_death_cross_enters_red_next_open_and_exits_fifth_close():
    prices = {"512100.SH": bars([10] * 8), "510880.SH": bars([5] * 8), "515220.SH": bars([5] * 8)}
    s = signals(8, death_at=0, momentum=-0.05)
    result = run_variant(prices, s, "severe_red", initial_cash=100_000, fees=no_fees())
    trades = result.trades
    assert trades[["date", "code", "side", "reason"]].values.tolist() == [
        ["20240507", "510880.SH", "buy", "severe_death_cross"],
        ["20240513", "510880.SH", "sell", "defensive_5_session_exit"],
    ]
    assert result.nav.loc[1, "510880.SH_quantity"] == 20_000
    assert result.nav.loc[5, "510880.SH_quantity"] == 0


def test_nonsevere_cross_stays_cash_but_half_mode_buys_both():
    prices = {"512100.SH": bars([10] * 3), "510880.SH": bars([5] * 3), "515220.SH": bars([5] * 3)}
    s = signals(3, death_at=0, momentum=-0.03)
    red = run_variant(prices, s, "severe_red", initial_cash=100_000, fees=no_fees())
    half = run_variant(prices, s, "half", initial_cash=100_000, fees=no_fees())
    assert red.trades.empty
    assert half.trades["code"].tolist() == ["510880.SH", "515220.SH"]


def test_new_primary_buy_signal_returns_from_defensive_next_open():
    prices = {"512100.SH": bars([10] * 5), "510880.SH": bars([5] * 5), "515220.SH": bars([5] * 5)}
    s = signals(5, death_at=0, momentum=-0.05, buy_at=2)
    result = run_variant(prices, s, "severe_red", initial_cash=100_000, fees=no_fees())
    assert result.trades[["date", "code", "side"]].values.tolist() == [
        ["20240507", "510880.SH", "buy"],
        ["20240509", "510880.SH", "sell"],
        ["20240509", "512100.SH", "buy"],
    ]


def test_primary_buy_uses_next_session_open_price():
    prices = {"512100.SH": bars([10, 12, 12]), "510880.SH": bars([5] * 3), "515220.SH": bars([5] * 3)}
    s = signals(3, death_at=2, momentum=-0.02, buy_at=0)
    result = run_variant(prices, s, "cash", initial_cash=100_000, fees=no_fees())
    assert result.trades.iloc[0]["date"] == "20240507"
    assert result.trades.iloc[0]["signal_price"] == 12


def test_red_dividend_keeps_nav_continuous_across_ex_date():
    dates = pd.to_datetime(["2024-01-19 15:00", "2024-01-22 15:00", "2024-01-23 15:00", "2024-01-26 15:00"])
    prices = {"512100.SH": bars([10] * 4), "510880.SH": bars([3, 3, 2.869, 2.869]),
              "515220.SH": bars([10] * 4)}
    for frame in prices.values():
        frame["date"] = dates
    s = pd.DataFrame({"date": dates.normalize(), "buy_signal": [False] * 4,
                      "exit_macd": [True, False, False, False],
                      "exit_ma10": [False] * 4, "momentum_3": [-0.05] * 4})
    result = run_variant(prices, s, "severe_red", initial_cash=100_000, fees=no_fees())
    assert result.nav.loc[1, "nav"] == pytest.approx(result.nav.loc[2, "nav"])
    assert result.nav.loc[2, "dividend_receivable"] > 0
    assert result.nav.loc[3, "dividend_receivable"] == 0


def test_coal_split_doubles_existing_units_without_nav_loss():
    dates = pd.to_datetime(["2024-04-10 15:00", "2024-04-11 15:00", "2024-04-12 15:00"])
    prices = {"512100.SH": bars([10] * 3), "510880.SH": bars([5] * 3),
              "515220.SH": bars([2, 2, 1])}
    for frame in prices.values():
        frame["date"] = dates
    s = pd.DataFrame({"date": dates.normalize(), "buy_signal": [False] * 3,
                      "exit_macd": [True, False, False], "exit_ma10": [False] * 3,
                      "momentum_3": [-0.02] * 3})
    result = run_variant(prices, s, "half", initial_cash=100_000, fees=no_fees())
    assert result.nav.loc[2, "515220.SH_quantity"] == 2 * result.nav.loc[1, "515220.SH_quantity"]
    assert result.nav.loc[2, "nav"] == pytest.approx(result.nav.loc[1, "nav"])
