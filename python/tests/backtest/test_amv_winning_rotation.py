from __future__ import annotations

import pandas as pd

from python.backtest.broker import FeeConfig
from python.strategies.amv_winning_rotation.runner import run_rotation_backtest


def _bars(code: str, closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=len(closes), freq="D")
    return pd.DataFrame({
        "date": dates + pd.Timedelta(hours=15),
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": 1_000_000, "code": code,
    })


def _fees() -> FeeConfig:
    return FeeConfig.etf_legacy().with_overrides(
        commission_rate=0, min_commission=0, slippage_rate=0,
    )


def test_death_cross_rotates_full_portfolio_and_next_buy_rotates_back() -> None:
    bars = {
        "512100.SH": _bars("512100.SH", [10.0] * 4),
        "510880.SH": _bars("510880.SH", [5.0] * 4),
        "515220.SH": _bars("515220.SH", [5.0] * 4),
    }
    signals = pd.DataFrame({
        "date": pd.date_range("2024-01-02", periods=4, freq="D"),
        "buy_signal": [True, False, False, True],
        "exit_ma10": [False] * 4,
        "exit_macd": [False, True, False, False],
    })

    result = run_rotation_backtest(bars, signals, initial_cash=100_000, fees=_fees())

    death_day = result.trades.loc[result.trades["date"] == "20240103"]
    assert death_day[["code", "side"]].values.tolist() == [
        ["512100.SH", "sell"], ["510880.SH", "buy"], ["515220.SH", "buy"],
    ]
    assert death_day.iloc[1]["quantity"] == 10_000
    assert death_day.iloc[2]["quantity"] == 10_000
    assert death_day.iloc[0]["hold_sessions"] == 1
    assert result.nav.iloc[1]["512100.SH_quantity"] == 0
    assert result.nav.iloc[1]["510880.SH_quantity"] == 10_000
    assert result.nav.iloc[1]["515220.SH_quantity"] == 10_000
    return_day = result.trades.loc[result.trades["date"] == "20240105"]
    assert return_day[["code", "side"]].values.tolist() == [
        ["510880.SH", "sell"], ["515220.SH", "sell"], ["512100.SH", "buy"],
    ]
    assert result.nav.iloc[-1]["nav"] == 100_000


def test_ma10_exit_stays_in_cash_until_death_cross_or_new_buy() -> None:
    bars = {code: _bars(code, [10.0] * 3) for code in
            ("512100.SH", "510880.SH", "515220.SH")}
    signals = pd.DataFrame({
        "date": pd.date_range("2024-01-02", periods=3, freq="D"),
        "buy_signal": [True, False, False],
        "exit_ma10": [False, True, False],
        "exit_macd": [False] * 3,
    })

    result = run_rotation_backtest(bars, signals, initial_cash=100_000, fees=_fees())

    assert result.trades[["code", "side"]].values.tolist() == [
        ["512100.SH", "buy"], ["512100.SH", "sell"],
    ]
    assert result.nav.iloc[-1]["cash"] == 100_000


def test_primary_hard_stop_still_sells_before_close_signal() -> None:
    bars = {code: _bars(code, [10.0, 10.0]) for code in
            ("512100.SH", "510880.SH", "515220.SH")}
    bars["512100.SH"].loc[1, "low"] = 9.7
    signals = pd.DataFrame({
        "date": pd.date_range("2024-01-02", periods=2, freq="D"),
        "buy_signal": [True, False],
        "exit_ma10": [False, False], "exit_macd": [False, False],
    })

    result = run_rotation_backtest(bars, signals, initial_cash=100_000, fees=_fees())

    assert result.trades.iloc[1]["reason"] == "hard_stop_2.5pct"
    assert result.trades.iloc[1]["signal_price"] == 9.75


def test_coal_split_doubles_existing_shares_without_changing_nav() -> None:
    bars = {
        "512100.SH": _bars("512100.SH", [10.0, 10.0]),
        "510880.SH": _bars("510880.SH", [10.0, 10.0]),
        "515220.SH": _bars("515220.SH", [2.0, 1.0]),
    }
    for frame in bars.values():
        frame["date"] = pd.to_datetime(["2024-04-11 15:00", "2024-04-12 15:00"])
    signals = pd.DataFrame({
        "date": pd.to_datetime(["2024-04-11", "2024-04-12"]),
        "buy_signal": [False, False],
        "exit_ma10": [False, False], "exit_macd": [True, False],
    })

    result = run_rotation_backtest(bars, signals, initial_cash=100_000, fees=_fees())

    assert result.nav.iloc[0]["515220.SH_quantity"] == 25_000
    assert result.nav.iloc[1]["515220.SH_quantity"] == 50_000
    assert result.nav.iloc[1]["nav"] == 100_000


def test_dividend_entitlement_offsets_ex_price_drop_until_cash_payment() -> None:
    bars = {
        "512100.SH": _bars("512100.SH", [10.0] * 3),
        "510880.SH": _bars("510880.SH", [3.0, 2.869, 2.869]),
        "515220.SH": _bars("515220.SH", [10.0] * 3),
    }
    dates = ["2024-01-22 15:00", "2024-01-23 15:00", "2024-01-26 15:00"]
    for frame in bars.values():
        frame["date"] = pd.to_datetime(dates)
    signals = pd.DataFrame({
        "date": pd.to_datetime([date[:10] for date in dates]),
        "buy_signal": [False] * 3,
        "exit_ma10": [False] * 3, "exit_macd": [True, False, False],
    })

    result = run_rotation_backtest(bars, signals, initial_cash=100_000, fees=_fees())

    assert result.nav.iloc[0]["nav"] == 100_000
    assert result.nav.iloc[1]["nav"] == 100_000
    assert result.nav.iloc[1]["dividend_receivable"] == 16_600 * 0.131
    assert result.nav.iloc[2]["dividend_receivable"] == 0
    assert result.nav.iloc[2]["cash"] == 200 + 16_600 * 0.131
