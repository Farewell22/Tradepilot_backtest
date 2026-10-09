from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from python.backtest.broker import FeeConfig
from python.strategies.amv_winning import runner as weekly
from python.strategies.amv_winning.bank_stock import load_stock_history
from python.strategies.amv_winning_defensive.runner import run_defensive_backtest


BANKS = [("amv_winning_ccb", "601939.SH", "建设银行"),
         ("amv_winning_cmb", "600036.SH", "招商银行")]


def bars(prices, dates=None):
    dates = pd.to_datetime(dates) if dates is not None else pd.bdate_range("2024-01-02", periods=len(prices))
    return pd.DataFrame({"date": dates + pd.Timedelta(hours=15), "open": prices,
                         "high": prices, "low": prices, "close": prices, "volume": 100_000})


def signals(primary, buys=(0,), exits=(1,)):
    return pd.DataFrame({"date": primary.date.dt.normalize(),
                         "buy_signal": [i in buys for i in range(len(primary))],
                         "exit_ma10": [i in exits for i in range(len(primary))], "exit_macd": False})


def free_fees():
    return FeeConfig(0, 0, 0, 0, 0)


@pytest.mark.parametrize("task,code,name", BANKS)
def test_new_banks_use_stock_dividends_and_no_etf_split(task, code, name):
    dates = ["2025-07-03", "2025-07-04", "2025-07-07", "2025-07-08"]
    primary, stock = bars([10.] * 4, dates), bars([5., 5., 4.5, 4.5], dates)
    dividend = {pd.Timestamp("2025-07-07"): .5}
    sig = signals(primary, buys=(0, 3))
    direct = run_defensive_backtest(primary, stock, sig, code, 100_000,
                                   free_fees(), free_fees(), dividend)
    j = weekly.run_bank_kdj_backtest(primary, stock, sig,
        pd.Series(0., index=primary.date.dt.normalize()), 100_000, free_fees(),
        bank_code=code, bank_fees=free_fees(), dividends=dividend)
    assert direct.nav.defensive_quantity.tolist() == [0, 20_000, 20_000, 0]
    assert j.nav.bank_quantity.tolist() == [0, 20_000, 20_000, 0]
    assert direct.nav.nav.tolist() == pytest.approx([100_000] * 4)
    assert j.nav.nav.tolist() == pytest.approx([100_000] * 4)
    assert direct.trades.query("code == @code and side == 'sell'").iloc[0].dividend_income == 10_000
    assert j.trades.query("code == @code").iloc[0].dividend_income == 10_000
    assert j.open_position["code"] == weekly.PRIMARY


@pytest.mark.parametrize("task,code,name", BANKS)
def test_direct_stock_net_take_profit_locks_cash_and_honors_t1(task, code, name):
    primary, stock = bars([10.] * 5), bars([5., 5., 5.4, 5.6, 5.6])
    stock.loc[1, "high"] = 6.  # Entry bar cannot be sold for a profit.
    fees = FeeConfig(0, 0, .01, 0, 0)
    result = run_defensive_backtest(primary, stock, signals(primary, exits=(1, 2, 3, 4)),
                                   code, 100_000, free_fees(), fees)
    sells = result.trades.query("code == @code and side == 'sell'")
    assert len(sells) == 1
    assert sells.iloc[0].date == "20240105"
    assert sells.iloc[0].pnl_pct == pytest.approx(10.88)
    assert result.nav.cash.iloc[-1] == pytest.approx(110_880)
    assert not result.open_positions


@pytest.mark.parametrize("task,code,name", BANKS)
def test_j_filter_is_strict_and_target_rounds_to_cent(task, code, name):
    primary, stock = bars([10.] * 5), bars([5.03] * 5)
    stock.loc[3, "high"] = 5.43
    stock.loc[4, "high"] = 5.44
    j = pd.Series([0., 10., 9.99, 9.99, 9.99], index=primary.date.dt.normalize())
    result = weekly.run_bank_kdj_backtest(primary, stock, signals(primary), j,
        100_000, free_fees(), bank_code=code, bank_fees=free_fees())
    assert result.nav.bank_quantity.iloc[:3].tolist() == [0, 0, 19_800]
    trade = result.trades.query("code == @code").iloc[0]
    assert trade.buy_date == "20240104"
    assert trade.sell_date == "20240108"
    assert trade.sell_signal_price == pytest.approx(5.44)
    assert trade.sell_reason == "bank_take_profit_8pct"


def write_stock_day(root, date, price, code):
    day = pd.Timestamp(date)
    times = list(pd.date_range(day + pd.Timedelta(hours=9, minutes=35), periods=24, freq="5min"))
    times += list(pd.date_range(day + pd.Timedelta(hours=13, minutes=5), periods=24, freq="5min"))
    frame = pd.DataFrame({"code": code, "trade_time": times, "open": price,
                          "high": price, "low": price, "close": price,
                          "vol": 100_000., "amount": price * 100_000})
    path = root / str(day.year) / f"{day:%Y%m%d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


@pytest.mark.parametrize("task,code,name", BANKS)
def test_stock_loader_filters_requested_bank_and_audits_its_raw_prices(tmp_path, task, code, name):
    path = write_stock_day(tmp_path, "2024-01-02", 5., code)
    source = pd.read_parquet(path)
    other = source.copy()
    other["code"], other["close"] = "601288.SH", 99.
    pd.concat([source, other]).to_parquet(path, index=False)
    loaded, audit = load_stock_history(tmp_path, pd.Timestamp("2024-01-02"), code=code)
    assert loaded.close.unique().tolist() == [5.]
    assert audit["code"] == code
    assert audit["vwap_in_bar_range_pct"] == 100


def comparison_inputs(tmp_path, code):
    dates = pd.date_range("2024-01-01", periods=14)
    primary = bars([10.] * 14, dates)
    amv = pd.DataFrame({"date": dates, "close": [100.] * 10 + [104.1, 90., 90., 90.]})
    history = list(pd.date_range(end="2023-12-29", periods=13, freq="W-FRI"))
    prices = [12.] * 8 + [10., 9., 8., 7., 6.] + [5.] * 14
    stock_dir = tmp_path / "stock"
    for date, price in zip(history + list(dates), prices, strict=True):
        write_stock_day(stock_dir, date, price, code)
    amv_path, primary_path = tmp_path / "amv.csv", tmp_path / "primary.csv"
    amv.to_csv(amv_path, index=False)
    primary.to_csv(primary_path, index=False)
    dividends = tmp_path / "dividends.csv"
    dividends.write_text("ex_date,cash_per_share,source\n2024-01-14,0.5,https://example.test/announcement\n")
    return amv_path, primary_path, stock_dir, dividends


@pytest.mark.parametrize("task,code,name", BANKS)
def test_registered_entry_runs_both_variants_on_own_bank_and_snapshots(tmp_path, task, code, name):
    from python.run_backtest import main
    from python.task_registry import TASKS
    amv, primary, stocks, dividends = comparison_inputs(tmp_path, code)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"paths": {
        "amv_csv": str(amv), "primary_csv": str(primary), "stock_5m_dir": str(stocks),
        "stock_dividends_csv": str(dividends)}, "initial_cash": 100_000,
        "bank_fees": {"commission_rate": 0, "min_commission": 0, "slippage_rate": 0,
                      "stamp_duty_rate": 0, "transfer_fee_rate": 0}}))
    from dataclasses import replace
    spec = replace(TASKS[("strategy", task)], report_dir=None)
    status = main(["run", "strategy", task, "--start", "20240110", "--end", "20240114",
                   "--config", str(config), "--output-root", str(tmp_path / "runs"),
                   "--commission-rate", "0", "--min-commission", "0", "--slippage-rate", "0"],
                  tasks={("strategy", task): spec})
    assert status == 0
    output = next((tmp_path / "runs").iterdir())
    metrics = json.loads((output / "metrics.json").read_text())
    for variant in ("direct", "weekly_j"):
        m = metrics["variants"][variant]
        assert m["bank_code"] == code
        assert m["dividend_income"] == 10_000
        assert m["sessions"] == 5
        nav = pd.read_csv(output / variant / "nav.csv")
        assert nav.nav.iloc[-1] == pytest.approx(110_000)
        assert set(nav.position_code) <= {code, weekly.PRIMARY, "cash"}
        assert (output / variant / "trades.csv").is_file()
        assert name in (output / variant / "report.md").read_text()
    assert json.loads((output / "run_manifest.json").read_text())["status"] == "complete"
    audit = json.loads((output / "source_manifest.json").read_text())
    assert audit["stock"]["code"] == code
    for path, checksum in audit["sha256"].items():
        assert hashlib.sha256((output / path).read_bytes()).hexdigest() == checksum
    assert (output / "inputs" / f"{code}.csv").is_file()


@pytest.mark.parametrize("missing", ["stock", "amv"])
def test_comparison_rejects_missing_primary_day(tmp_path, missing):
    from python.strategies.amv_winning.bank_comparison import run_comparison
    amv, primary, stocks, dividends = comparison_inputs(tmp_path, "601939.SH")
    if missing == "stock":
        (stocks / "2024/20240113.parquet").unlink()
    else:
        frame = pd.read_csv(amv)
        frame.drop(index=12).to_csv(amv, index=False)
    with pytest.raises(ValueError, match="缺少.*交易日"):
        run_comparison(amv, primary, stocks, dividends, tmp_path / "run", bank_code="601939.SH",
                       bank_name="建设银行", start_date="20240110", end_date="20240114")


def test_no_trade_interval_keeps_all_csv_ledgers_readable(tmp_path):
    from python.strategies.amv_winning.bank_comparison import run_comparison
    amv, primary, stocks, dividends = comparison_inputs(tmp_path, "601939.SH")
    output = tmp_path / "run"
    metrics = run_comparison(amv, primary, stocks, dividends, output, bank_code="601939.SH",
        bank_name="建设银行", start_date="20240101", end_date="20240109")
    for path in ("direct/events.csv", "original_trades.csv", "direct/trades.csv", "weekly_j/trades.csv"):
        frame = pd.read_csv(output / path)
        assert frame.empty
        assert len(frame.columns) > 0
    for m in metrics["variants"].values():
        assert m["final_nav"] == 200_000
        assert m["closed_trade_count"] == 0


def test_missing_stock_warmup_fails_instead_of_silently_disabling_j_buys(tmp_path):
    from python.strategies.amv_winning.bank_comparison import run_comparison
    amv, primary, stocks, dividends = comparison_inputs(tmp_path, "601939.SH")
    for path in stocks.glob("2023/*.parquet"):
        path.unlink()
    with pytest.raises(ValueError, match="预热"):
        run_comparison(amv, primary, stocks, dividends, tmp_path / "run", bank_code="601939.SH",
                       bank_name="建设银行", start_date="20240110", end_date="20240114")
