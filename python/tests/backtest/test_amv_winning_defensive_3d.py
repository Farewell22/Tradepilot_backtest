from __future__ import annotations

import importlib
import json

import pandas as pd
import pytest
import yaml

from python.backtest.broker import FeeConfig
from python.run_backtest import RunRequest
from python.task_registry import TASKS


def strategy():
    assert ("strategy", "amv_winning_defensive_3d") in TASKS
    return importlib.import_module("python.strategies.amv_winning_defensive_3d.runner")


@pytest.mark.parametrize("tail,want", [
    ([101., 102., 104.5], True),  # Exactly +4.5% across three sessions.
    ([101., 102., 104.49], False),
    ([99., 101., 103.2], False),  # Two-day +4.24% must no longer suffice.
    ([100., 95., 99.], True),  # One-day +4.21% still works despite weak three-day return.
])
def test_primary_entry_uses_three_sessions_and_preserves_single_day(tail, want):
    amv = pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=13),
                        "close": [100.] * 10 + tail})
    signals = strategy().generate_amv_signals(amv)
    assert bool(signals.buy_signal.iloc[-1]) is want
    assert signals.three_day_return.iloc[-1] == pytest.approx(tail[-1] / 100 - 1)


def test_signal_has_no_future_dependency_or_premature_three_day_value():
    amv = pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=13),
                        "close": [100.] * 10 + [101., 102., 104.5]})
    runner = strategy()
    prefix = runner.generate_amv_signals(amv)
    future = pd.DataFrame({"date": pd.bdate_range("2024-01-19", periods=3),
                           "close": [300., 10., 500.]})
    full = runner.generate_amv_signals(pd.concat([amv, future], ignore_index=True))
    pd.testing.assert_frame_equal(prefix, full.iloc[:len(prefix)].reset_index(drop=True))
    assert prefix.three_day_return.iloc[:3].isna().all()


def fixture_paths(tmp_path):
    dates = pd.bdate_range("2024-01-02", periods=15)
    amv = pd.DataFrame({"date": dates, "close": [100.] * 10 + [101., 102., 104.5, 97., 97.]})
    primary = pd.DataFrame({"date": dates + pd.Timedelta(hours=15), "open": 10.,
                            "high": 10., "low": 10., "close": 10., "volume": 100000})
    stock = primary.copy()
    stock[["open", "high", "low", "close"]] = 5.
    stock.loc[14, ["open", "high", "low", "close"]] = [5., 5.5, 5., 5.5]
    dividends = pd.DataFrame({"ex_date": ["2024-01-01"], "cash_per_share": [.1],
                              "source": ["fixture"]})
    frames = {"amv_csv": amv, "primary_csv": primary, "stock_data": stock,
              "stock_dividends_csv": dividends}
    paths = {}
    for name, frame in frames.items():
        path = tmp_path / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = str(path)
    return paths, dates


def test_runner_executes_new_entry_then_original_bank_take_profit(tmp_path):
    runner = strategy()
    paths, dates = fixture_paths(tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"paths": paths, "initial_cash": 100000,
                                      "bank_fees": {"stamp_duty_rate": 0, "transfer_fee_rate": 0}}))
    output = tmp_path / "run"
    request = RunRequest("amv_winning_defensive_3d", "strategy", "20240102", "20240131",
                         output, FeeConfig(0, 0, 0, 0, 0), "legacy_same_close_idealized", config)
    assert runner.run(request) == output
    trades = pd.read_csv(output / "trades.csv", dtype={"date": str})
    assert trades[["code", "side", "reason"]].values.tolist() == [
        ["512100.SH", "buy", "amv_buy_signal"],
        ["512100.SH", "sell", "amv_close_below_ma10"],
        ["601288.SH", "buy", "amv_close_below_ma10"],
        ["601288.SH", "sell", "bank_take_profit_8pct"],
    ]
    assert trades.iloc[0].date == dates[12].strftime("%Y%m%d")
    assert trades.iloc[-1].signal_price == pytest.approx(5.4)
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["final_nav"] == pytest.approx(108000)
    assert metrics["has_open_position"] is False
    assert len(pd.read_csv(output / "baseline/nav.csv")) == 15
    assert (output / "inputs/0AMV.csv").is_file()
    assert (output / "code_snapshot/python/strategies/amv_winning_defensive_3d/runner.py").is_file()


def test_runner_rejects_missing_stock_session_instead_of_shortening_calendar(tmp_path):
    runner = strategy()
    paths, _ = fixture_paths(tmp_path)
    stock = pd.read_csv(paths["stock_data"])
    stock.iloc[:-1].to_csv(paths["stock_data"], index=False)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"paths": paths}))
    request = RunRequest("amv_winning_defensive_3d", "strategy", "20240102", "20240131",
                         tmp_path / "run", FeeConfig.etf_legacy(), "legacy_same_close_idealized", config)
    with pytest.raises(ValueError, match="缺少"):
        runner.run(request)
