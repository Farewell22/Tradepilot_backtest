from __future__ import annotations

import importlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from python.backtest.broker import FeeConfig
from python.run_backtest import ROOT, RunRequest


def strategy():
    path = ROOT / "python/strategies/amv_winning_defensive_ma20_entry/runner.py"
    assert path.exists(), "MA20确认第二买点实验尚未实现"
    return importlib.import_module("python.strategies.amv_winning_defensive_ma20_entry.runner")


def amv(closes):
    return pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=len(closes)),
                         "close": closes})


def test_confirmation_waits_until_fifth_session_and_does_not_backdate_entry():
    signals = strategy().generate_amv_signals(amv([100.] * 60 + [101., 101., 101., 104., 105.2]))
    assert signals.iloc[60:64].second_entry.tolist() == [False] * 4
    last = signals.iloc[-1]
    assert last.second_entry and last.buy_signal and not last.single_day_entry
    assert last.entry_branch == "ma20_confirmation_5d"
    assert last.momentum_3 == pytest.approx(105.2 / 101. - 1)


def test_confirmation_expires_before_sixth_session():
    signals = strategy().generate_amv_signals(amv([100.] * 60 + [101.] * 5 + [106.]))
    assert not signals.second_entry.any()
    assert signals.iloc[-1].single_day_entry


def test_long_term_ma60_blocks_confirmation_in_downtrend():
    signals = strategy().generate_amv_signals(amv([200.] * 40 + [100.] * 20 +
                                                 [101., 101., 101., 104., 105.2]))
    assert signals.iloc[-1].momentum_3 > .04
    assert signals.iloc[-1].close < signals.iloc[-1].ma60
    assert not signals.second_entry.any()


def test_three_day_return_exactly_four_percent_does_not_confirm():
    signals = strategy().generate_amv_signals(amv([100.] * 60 + [101., 102., 104.]))
    last = signals.iloc[-1]
    assert last.momentum_3 == pytest.approx(.04)
    assert not last.single_day_entry
    assert not last.second_entry and not last.buy_signal


def test_original_daily_signal_wins_attribution_when_both_entries_confirm():
    signals = strategy().generate_amv_signals(amv([100.] * 60 + [105.]))
    assert signals.iloc[-1].second_entry and signals.iloc[-1].single_day_entry
    assert signals.iloc[-1].entry_branch == "single_day_ge_4pct"


def test_future_prices_cannot_change_past_confirmation_signals():
    runner = strategy()
    prices = [100.] * 60 + [101., 101., 101., 104., 105.2]
    history = runner.generate_amv_signals(amv(prices))
    for length in (61, 63, 64, 65):
        prefix = runner.generate_amv_signals(amv(prices[:length]))
        pd.testing.assert_frame_equal(prefix, history.iloc[:length].reset_index(drop=True))
    extended = runner.generate_amv_signals(amv(prices + [50., 2000., 3000.]))
    pd.testing.assert_frame_equal(history, extended.iloc[:len(history)].reset_index(drop=True))


def test_real_runner_next_open_t1_rotation_and_branch_statistics(tmp_path):
    runner = strategy()
    history = amv([100.] * 60 + [101., 101., 101., 104., 105.2, 90., 106., 107.])
    dates = history.date.iloc[-4:].reset_index(drop=True)
    primary = pd.DataFrame({"date": dates + pd.Timedelta(hours=15),
                            "open": [10., 12., 13., 10.], "high": [10., 12., 13., 10.],
                            "low": [10., 9., 13., 10.], "close": [10., 12., 13., 10.],
                            "volume": 100000})
    stock = primary.copy()
    stock[["open", "high", "low", "close"]] = 5.
    dividends = pd.DataFrame({"ex_date": dates.iloc[2:].tolist(),
                              "cash_per_share": [.1, .1], "source": ["fixture", "fixture"]})
    paths = {}
    for key, frame in {"amv_csv": history, "primary_csv": primary, "stock_data": stock,
                       "stock_dividends_csv": dividends}.items():
        path = tmp_path / f"{key}.csv"
        frame.to_csv(path, index=False)
        paths[key] = str(path)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"paths": paths, "initial_cash": 100000,
                                      "bank_fees": {"stamp_duty_rate": 0, "transfer_fee_rate": 0}}))
    output = tmp_path / "run"
    runner.run(RunRequest("amv_winning_defensive_ma20_entry", "strategy",
                         dates.iloc[0].strftime("%Y%m%d"), dates.iloc[-1].strftime("%Y%m%d"),
                         output, FeeConfig(0, 0, 0, 0, 0), "next_open_amv_abc_t1", config))
    events = pd.read_csv(output / "trades.csv", dtype={"date": str, "signal_date": str})
    assert events[["code", "side"]].values.tolist() == [
        ["512100.SH", "buy"], ["512100.SH", "sell"], ["601288.SH", "buy"],
        ["601288.SH", "sell"], ["512100.SH", "buy"],
    ]
    buys = events[(events.code == "512100.SH") & (events.side == "buy")]
    assert buys.entry_branch.tolist() == ["ma20_confirmation_5d", "single_day_ge_4pct"]
    assert buys.date.tolist() == dates.iloc[[1, 3]].dt.strftime("%Y%m%d").tolist()
    assert buys.signal_date.tolist() == dates.iloc[[0, 2]].dt.strftime("%Y%m%d").tolist()
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["final_nav"] == pytest.approx(110460)
    assert metrics["dividend_income"] == pytest.approx(2160)
    assert metrics["parameters"]["second_entry"] == "ma20_confirmation_5d"
    assert metrics["parameters"]["confirmation_window_sessions"] == 5
    assert (output / "baseline/metrics.json").exists()
    pairs = pd.read_csv(output / "primary_trades.csv")
    assert len(pairs) == 1 and pairs.iloc[0].entry_branch == "ma20_confirmation_5d"
    stats = pd.read_csv(output / "signal_trade_stats.csv")
    second = stats.loc[stats.entry_branch.eq("ma20_confirmation_5d")].iloc[0]
    assert second.closed_positions == 1 and second.win_rate_pct == 100
    verify = json.loads((output / "verification.json").read_text())
    assert verify["next_open_signal_dates_before_fills"]


@pytest.mark.parametrize("sessions,want_buys", [(1, 0), (2, 1)])
def test_runner_exports_no_trades_or_only_unclosed_position(tmp_path, sessions, want_buys):
    history = amv([100.] * 60 + [105., 105.1][:sessions])
    dates = history.date.iloc[-sessions:].reset_index(drop=True)
    primary = pd.DataFrame({"date": dates + pd.Timedelta(hours=15),
                            "open": 10., "high": 10., "low": 10., "close": 10., "volume": 100000})
    stock = primary.copy()
    stock[["open", "high", "low", "close"]] = 5.
    frames = {"amv_csv": history, "primary_csv": primary, "stock_data": stock,
              "stock_dividends_csv": pd.DataFrame(columns=["ex_date", "cash_per_share", "source"])}
    paths = {}
    for key, frame in frames.items():
        path = tmp_path / f"{key}.csv"
        frame.to_csv(path, index=False)
        paths[key] = str(path)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"paths": paths, "initial_cash": 100000,
                                      "bank_fees": {"stamp_duty_rate": 0, "transfer_fee_rate": 0}}))
    output = tmp_path / "run"
    request = RunRequest("amv_winning_defensive_ma20_entry", "strategy",
                         dates.iloc[0].strftime("%Y%m%d"), dates.iloc[-1].strftime("%Y%m%d"),
                         output, FeeConfig(0, 0, 0, 0, 0), "next_open_amv_abc_t1", config)
    strategy().run(request)
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["final_nav"] == 100000
    assert metrics["primary_entry_count"] == want_buys
    assert metrics["closed_trade_count"] == 0
    assert metrics["open_positions"] == ({"512100.SH": 10000} if want_buys else {})
    assert pd.read_csv(output / "primary_trades.csv").empty
