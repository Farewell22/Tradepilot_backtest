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
    assert ("strategy", "amv_winning_defensive_single_day") in TASKS
    return importlib.import_module("python.strategies.amv_winning_defensive_single_day.runner")


@pytest.mark.parametrize("tail,want", [
    ([101., 102., 104.5], False),  # Three-day +4.5% alone is insufficient.
    ([99., 101., 103.2], False),  # Two-day +4.24% alone is insufficient.
    ([100., 100., 104.], True),  # Exact one-day +4% remains inclusive.
    ([100., 100., 103.99], False),
    ([100., 90., 94.], False),  # +4.44% today, but close below MA5.
])
def test_entry_requires_single_day_four_percent_and_original_ma5(tail, want):
    amv = pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=13),
                        "close": [100.] * 10 + tail})
    signals = strategy().generate_amv_signals(amv)
    assert bool(signals.buy_signal.iloc[-1]) is want


def test_runner_rejects_multi_day_entry_but_rotates_after_later_single_day_signal(tmp_path):
    runner = strategy()
    dates = pd.bdate_range("2024-01-02", periods=17)
    amv = pd.DataFrame({"date": dates,
                        "close": [100.] * 10 + [101., 102., 104.5, 97., 97., 105., 105.]})
    primary = pd.DataFrame({"date": dates + pd.Timedelta(hours=15), "open": 10.,
                            "high": 10., "low": 10., "close": 10., "volume": 100000})
    stock = primary.copy()
    stock[["open", "high", "low", "close"]] = 5.
    dividends = pd.DataFrame({"ex_date": [dates[14]], "cash_per_share": [.1], "source": ["fixture"]})
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
    request = RunRequest("amv_winning_defensive_single_day", "strategy", "20240102", "20240131",
                         output, FeeConfig(0, 0, 0, 0, 0), "legacy_same_close_idealized", config)
    runner.run(request)
    events = pd.read_csv(output / "trades.csv", dtype={"date": str})
    assert events[["code", "side", "reason"]].values.tolist() == [
        ["601288.SH", "buy", "amv_close_below_ma10"],
        ["601288.SH", "sell", "amv_buy_signal_rotate_back"],
        ["512100.SH", "buy", "amv_buy_signal"],
    ]
    assert events.iloc[-1].date == dates[15].strftime("%Y%m%d")
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["final_nav"] == pytest.approx(102000)
    assert metrics["dividend_income"] == pytest.approx(2000)
    assert metrics["parameters"]["multi_day_sessions"] is None
    assert metrics["parameters"]["multi_day_threshold"] is None
    assert (output / "code_snapshot/python/strategies/amv_winning_defensive_single_day/runner.py").is_file()
