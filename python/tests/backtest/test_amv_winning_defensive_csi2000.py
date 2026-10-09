from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from python.backtest.broker import FeeConfig
from python.run_backtest import main
from python.strategies.amv_winning.bank_comparison import _paired_events
from python.strategies.amv_winning.bank_stock import snapshot_stock_inputs
from python.strategies.amv_winning_defensive.runner import run_defensive_backtest


ZERO = FeeConfig(0, 0, 0, 0, 0)


def bars(prices, start="2024-01-02"):
    return pd.DataFrame({
        "date": pd.bdate_range(start, periods=len(prices)) + pd.Timedelta(hours=15),
        "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": 100000,
    })


def signals(days, buys=(), exits=(), start="2024-01-02"):
    return pd.DataFrame({
        "date": pd.bdate_range(start, periods=days),
        "buy_signal": [i in buys for i in range(days)],
        "exit_ma10": [i in exits for i in range(days)], "exit_macd": False,
    })


def test_new_primary_rotates_and_bank_profit_locks_cash_with_dividends():
    result = run_defensive_backtest(
        bars([10.] * 6), bars([5., 5., 5.5, 5., 5., 5.]),
        signals(6, buys=(0, 4), exits=(1, 2, 3, 5)), "601288.SH",
        100000, ZERO, ZERO, {pd.Timestamp("2024-01-04"): .1},
        primary_code="563300.SH",
    )
    assert result.trades[["code", "side"]].values.tolist() == [
        ["563300.SH", "buy"], ["563300.SH", "sell"], ["601288.SH", "buy"],
        ["601288.SH", "sell"], ["563300.SH", "buy"],
        ["563300.SH", "sell"], ["601288.SH", "buy"],
    ]
    assert result.trades.iloc[3].reason == "bank_take_profit_8pct"
    assert result.nav.iloc[2]["nav"] == pytest.approx(112000)  # 10% gap gain + 2% dividend.
    assert result.nav.iloc[3]["cash"] == pytest.approx(112000)
    assert result.nav.iloc[3].defensive_quantity == 0
    assert result.nav.iloc[-1].dividend_income == pytest.approx(2000)


def test_new_primary_stop_holds_cash_and_blocks_same_day_reentry():
    primary = bars([10., 10., 10.])
    primary.loc[1, "low"] = 9.7
    result = run_defensive_backtest(
        primary, bars([5.] * 3), signals(3, buys=(0, 1)), "601288.SH",
        100000, ZERO, ZERO, primary_code="563300.SH",
    )
    assert result.trades.iloc[-1].reason == "hard_stop_2.5pct"
    assert result.trades.iloc[-1].signal_price == pytest.approx(9.75)
    assert len(result.trades) == 2
    assert result.nav.iloc[-1]["cash"] == pytest.approx(97500)
    assert result.open_positions == {}


def test_new_primary_does_not_receive_512100_consolidation():
    primary = bars([10., 10.], start="2022-09-01")
    result = run_defensive_backtest(
        primary, bars([5., 5.], start="2022-09-01"),
        signals(2, buys=(0,), start="2022-09-01"), "601288.SH",
        100000, ZERO, ZERO, primary_code="563300.SH",
    )
    assert result.open_positions == {"563300.SH": 10000}
    assert result.nav.iloc[-1]["nav"] == pytest.approx(100000)


def test_new_primary_pairing_uses_etf_fees():
    result = run_defensive_backtest(
        bars([10., 10.]), bars([5., 5.]), signals(2, buys=(0,), exits=(1,)),
        "601288.SH", 100000, ZERO, ZERO, primary_code="563300.SH",
    )
    pairs = _paired_events(result.trades, ZERO, FeeConfig.stock_legacy(), primary_code="563300.SH")
    assert pairs.iloc[0].sell_stamp_duty == 0
    assert pairs.iloc[0].buy_transfer_fee == 0
    assert pairs.iloc[0].pnl == 0


def test_snapshot_labels_both_primary_inputs_and_hashes(tmp_path):
    amv, primary, baseline, dividends = [tmp_path / name for name in (
        "amv.csv", "new.csv", "old.csv", "dividends.csv")]
    for path, contents in ((amv, "amv"), (primary, "new"), (baseline, "old"), (dividends, "dividends")):
        path.write_text(contents)
    output = tmp_path / "output"
    snapshot_stock_inputs(
        output, bars([5.]), dividends, {}, amv_path=amv, primary_path=primary,
        primary_code="563300.SH", extra_inputs={"512100.SH.csv": baseline},
    )
    assert (output / "inputs/563300.SH.csv").read_text() == "new"
    assert (output / "inputs/512100.SH.csv").read_text() == "old"
    manifest = json.loads((output / "source_manifest.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest


def fixture_config(tmp_path, *, empty_trades=False):
    dates = pd.bdate_range("2024-01-02", periods=15)
    amv = pd.DataFrame({"date": dates, "close": [100.] * 10 + [105., 105., 95., 95., 95.]})
    if empty_trades:
        amv["close"] = 100.
    primary = bars([10.] * 5, start="2024-01-16")
    baseline = bars([20.] * 5, start="2024-01-16")
    stock = bars([5., 5., 5., 5.5, 5.5], start="2024-01-16")
    frames = {"amv_csv": amv, "primary_csv": primary, "baseline_primary_csv": baseline,
              "stock_dividends_csv": pd.DataFrame({"ex_date": ["2024-01-19"],
                                                    "cash_per_share": [.1], "source": ["fixture"]})}
    paths = {}
    for key, frame in frames.items():
        path = tmp_path / f"{key}.csv"
        frame.to_csv(path, index=False)
        paths[key] = str(path)
    stock_dir = tmp_path / "stock"
    for row in stock.to_dict("records"):
        date = row.pop("date")
        target = stock_dir / str(date.year) / f"{date:%Y%m%d}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        row.update(code="601288.SH", trade_time=date, vol=row.pop("volume"))
        pd.DataFrame([row]).to_parquet(target, index=False)
    paths["stock_5m_dir"] = str(stock_dir)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"paths": paths, "initial_cash": 100000}))
    return config, paths


@pytest.mark.parametrize("variant,primary_code", [("csi2000", "563300.SH"), ("chinext", "159915.SZ")])
def test_registered_cli_runs_both_primaries_and_publishes(tmp_path, variant, primary_code):
    from dataclasses import replace
    from python.task_registry import TASKS

    config, _ = fixture_config(tmp_path)
    key = ("strategy", f"amv_winning_defensive_{variant}")
    spec = replace(TASKS[key], report_dir=tmp_path / "published")
    assert main(["run", *key, "--config", str(config), "--start", "20240116", "--end", "20240122",
                 "--output-root", str(tmp_path / "runs"), "--commission-rate", "0",
                 "--min-commission", "0", "--slippage-rate", "0"], tasks={key: spec}) == 0
    output = next((tmp_path / "runs").iterdir())
    new = pd.read_csv(output / "trades.csv")
    old = pd.read_csv(output / "baseline/trades.csv")
    assert set(new.code) == {primary_code, "601288.SH"}
    assert set(old.code) == {"512100.SH", "601288.SH"}
    assert new.iloc[0].date == 20240116  # Entry uses pre-start AMV warm-up.
    assert new.iloc[-1].reason == "bank_take_profit_8pct"
    nav = pd.read_csv(output / "nav.csv")
    pd.testing.assert_frame_equal(
        nav.drop(columns="primary_quantity"),
        pd.read_csv(output / "baseline/nav.csv").replace("512100.SH", primary_code).drop(columns="primary_quantity"),
    )
    assert len(nav) == 5
    assert nav.iloc[-1].dividend_income == pytest.approx(1990.)
    assert (output / "annual_returns.csv").is_file()
    assert f"{variant}_return_pct" in pd.read_csv(output / "annual_returns.csv")
    assert (output / f"inputs/{primary_code}.csv").is_file()
    assert (output / f"code_snapshot/python/strategies/amv_winning_defensive_{variant}/runner.py").is_file()
    assert len(pd.read_csv(output / "comparison_nav.csv")) == 5
    assert json.loads((output / "run_manifest.json").read_text())["status"] == "complete"
    assert (tmp_path / "published/latest-report.md").is_file()


@pytest.mark.parametrize("missing", ["primary_csv", "baseline_primary_csv", "amv_csv", "stock_5m_dir"])
@pytest.mark.parametrize("variant", ["csi2000", "chinext"])
def test_runner_rejects_missing_interior_session(tmp_path, missing, variant):
    from python.run_backtest import RunRequest

    runner = importlib.import_module(f"python.strategies.amv_winning_defensive_{variant}.runner")
    config, paths = fixture_config(tmp_path)
    if missing == "stock_5m_dir":
        (Path(paths[missing]) / "2024/20240118.parquet").unlink()
    else:
        frame = pd.read_csv(paths[missing])
        frame = frame.loc[~pd.to_datetime(frame.date).dt.normalize().eq(pd.Timestamp("2024-01-18"))]
        frame.to_csv(paths[missing], index=False)
    request = RunRequest(f"amv_winning_defensive_{variant}", "strategy", "20240116", "20240122",
                         tmp_path / "output", ZERO, "legacy_same_close_idealized", config)
    with pytest.raises(ValueError, match="缺少"):
        runner.run(request)


@pytest.mark.parametrize("empty", [True, False])
@pytest.mark.parametrize("variant", ["csi2000", "chinext"])
def test_runner_handles_no_trades_or_open_position(tmp_path, empty, variant):
    from python.run_backtest import RunRequest

    runner = importlib.import_module(f"python.strategies.amv_winning_defensive_{variant}.runner")
    config, _ = fixture_config(tmp_path, empty_trades=empty)
    request = RunRequest(f"amv_winning_defensive_{variant}", "strategy", "20240116", "20240117",
                         tmp_path / "output", ZERO, "legacy_same_close_idealized", config)
    runner.run(request)
    metrics = json.loads((request.output_dir / "metrics.json").read_text())
    assert metrics["closed_trade_count"] == 0
    assert metrics["has_open_position"] is (not empty)
    assert metrics["final_nav"] == pytest.approx(100000)
    assert len(pd.read_csv(request.output_dir / "nav.csv")) == 2
    assert (request.output_dir / "report.md").is_file()
