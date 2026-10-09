from __future__ import annotations

import importlib
import json

import pandas as pd
import pytest
import yaml

from python.backtest.broker import FeeConfig
from python.run_backtest import RunRequest
from python.strategies.amv_winning_defensive.runner import run_defensive_backtest


def strategy():
    return importlib.import_module("python.strategies.amv_winning_defensive_second_entry.runner")


def warm_amv(bump=.08):
    return pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=301),
                         "close": [100 + .1 * i for i in range(300)] + [130 + bump]})


@pytest.mark.parametrize("bump,want", [(.05, False), (.08, True), (.10, True), (.11, False)])
def test_second_entry_selects_middle_high_gap_without_daily_four_percent(bump, want):
    # On the increasing linear history, these final bumps fall below P60,
    # within P60-P80, within P60-P80, and above P80 respectively.
    signals = strategy().generate_amv_signals(warm_amv(bump))
    last = signals.iloc[-1]
    assert not last.single_day_entry
    assert bool(last.second_entry) is want
    assert bool(last.buy_signal) is want
    if want:
        assert last.entry_branch == "class_2_gap"


def test_second_entry_uses_only_prior_history():
    runner = strategy()
    amv = warm_amv()
    before = runner.generate_amv_signals(amv)
    extended = pd.concat([amv, pd.DataFrame({
        "date": pd.bdate_range(amv.date.iloc[-1] + pd.Timedelta(days=1), periods=10),
        "close": [1000.] * 10,
    })], ignore_index=True)
    after = runner.generate_amv_signals(extended).iloc[:len(amv)]
    pd.testing.assert_frame_equal(before, after)


def bars(prices):
    dates = pd.bdate_range("2024-01-02", periods=len(prices))
    return pd.DataFrame({"date": dates + pd.Timedelta(hours=15), "open": prices,
                         "high": prices, "low": prices, "close": prices, "volume": 100000})


def manual_signals(buys=(), exits=(), days=4):
    return pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=days),
                         "buy_signal": [i in buys for i in range(days)],
                         "exit_ma10": [i in exits for i in range(days)],
                         "exit_macd": False})


def test_next_open_fill_and_t1_stop_use_execution_day_prices():
    primary = bars([10., 12., 11., 11.])
    primary.loc[1, "low"] = 9.
    result = run_defensive_backtest(
        primary, bars([5.] * 4), manual_signals(buys=(0,)), "601288.SH",
        100000, FeeConfig(0, 0, 0, 0, 0), FeeConfig(0, 0, 0, 0, 0),
        execution_timing="next_open",
    )
    assert result.trades[["date", "side", "time"]].values.tolist() == [
        ["20240103", "buy", "open"], ["20240104", "sell", "15:00"],
    ]
    assert result.trades.iloc[0].signal_price == 12.
    assert result.trades.iloc[0].quantity == 8300
    assert result.trades.iloc[1].reason == "hard_stop_2.5pct"
    assert result.trades.iloc[1].signal_price == 11.
    assert result.nav.iloc[-1].nav == 91700.


def test_next_open_exit_has_priority_over_entry_and_bank_tp_lock_is_retained():
    signals = manual_signals(buys=(0, 1, 5), exits=(1, 3, 4), days=7)
    result = run_defensive_backtest(
        bars([10.] * 7), bars([5., 5., 5., 5.4, 5.4, 5.4, 5.4]), signals,
        "601288.SH", 100000, FeeConfig(0, 0, 0, 0, 0), FeeConfig(0, 0, 0, 0, 0),
        execution_timing="next_open",
    )
    assert result.trades[["date", "code", "side", "reason"]].values.tolist() == [
        ["20240103", "512100.SH", "buy", "amv_buy_signal"],
        ["20240104", "512100.SH", "sell", "amv_close_below_ma10"],
        ["20240104", "601288.SH", "buy", "amv_close_below_ma10"],
        ["20240105", "601288.SH", "sell", "bank_take_profit_8pct"],
        ["20240110", "512100.SH", "buy", "amv_buy_signal"],
    ]
    assert result.nav.iloc[4].cash == 108000.


def test_runner_executes_second_entry_then_rotates_from_bank_on_single_day_signal(tmp_path):
    runner = strategy()
    amv = warm_amv()
    extra_dates = pd.bdate_range(amv.date.iloc[-1] + pd.Timedelta(days=1), periods=3)
    amv = pd.concat([amv, pd.DataFrame({"date": extra_dates,
                                      "close": [120., 130.08, 130.2]})], ignore_index=True)
    dates = amv.date.iloc[-4:].reset_index(drop=True)
    primary = pd.DataFrame({"date": dates + pd.Timedelta(hours=15),
                            "open": [10., 12., 13., 10.], "high": [10., 12., 13., 10.],
                            "low": [10., 12., 13., 10.], "close": [10., 12., 13., 10.],
                            "volume": 100000})
    stock = primary.copy()
    stock[["open", "high", "low", "close"]] = 5.
    dividends = pd.DataFrame({"ex_date": dates.iloc[2:].tolist(),
                              "cash_per_share": [.1, .1], "source": ["fixture", "fixture"]})
    paths = {}
    for key, frame in {"amv_csv": amv, "primary_csv": primary, "stock_data": stock,
                       "stock_dividends_csv": dividends}.items():
        path = tmp_path / f"{key}.csv"
        frame.to_csv(path, index=False)
        paths[key] = str(path)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"paths": paths, "initial_cash": 100000,
                                      "bank_fees": {"stamp_duty_rate": 0, "transfer_fee_rate": 0}}))
    output = tmp_path / "run"
    runner.run(RunRequest("amv_winning_defensive_second_entry", "strategy",
                         dates.iloc[0].strftime("%Y%m%d"), dates.iloc[-1].strftime("%Y%m%d"),
                         output, FeeConfig(0, 0, 0, 0, 0), "next_open_amv_abc_t1", config))
    events = pd.read_csv(output / "trades.csv", dtype={"date": str, "signal_date": str})
    assert events[["code", "side"]].values.tolist() == [
        ["512100.SH", "buy"], ["512100.SH", "sell"], ["601288.SH", "buy"],
        ["601288.SH", "sell"], ["512100.SH", "buy"],
    ]
    buys = events[(events.code == "512100.SH") & (events.side == "buy")]
    assert buys.entry_branch.tolist() == ["class_2_gap", "single_day_ge_4pct"]
    assert buys.date.tolist() == dates.iloc[[1, 3]].dt.strftime("%Y%m%d").tolist()
    assert buys.signal_date.tolist() == dates.iloc[[0, 2]].dt.strftime("%Y%m%d").tolist()
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["final_nav"] == pytest.approx(110460)
    assert metrics["dividend_income"] == pytest.approx(2160)
    assert metrics["parameters"]["multi_day_sessions"] is None
    assert (output / "baseline/metrics.json").exists()
    assert (output / "legacy_same_close/second_entry/metrics.json").exists()
    pairs = pd.read_csv(output / "primary_trades.csv")
    assert len(pairs) == 1 and pairs.iloc[0].entry_branch == "class_2_gap"
