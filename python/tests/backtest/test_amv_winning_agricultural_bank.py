from __future__ import annotations

import math
import json
from pathlib import Path

import pandas as pd
import pytest

from python.backtest.broker import FeeConfig, calc_buy_cost, calc_sell_proceeds
from python.factors.z_indicators import compute_dynamic_weekly_kdj
from python.strategies.amv_winning import runner


STOCK = "601288.SH"


def bars(prices, dates=None):
    dates = pd.to_datetime(dates) if dates else pd.bdate_range("2024-01-02", periods=len(prices))
    return pd.DataFrame({"date": dates + pd.Timedelta(hours=15), "open": prices,
                         "high": prices, "low": prices, "close": prices, "volume": 1_000_000})


def signals(primary, buys=(0,), exits=(1,)):
    return pd.DataFrame({"date": primary["date"].dt.normalize(),
                         "buy_signal": [i in buys for i in range(len(primary))],
                         "exit_ma10": [i in exits for i in range(len(primary))], "exit_macd": False})


def free_fees():
    return FeeConfig.etf_legacy().with_overrides(commission_rate=0, min_commission=0, slippage_rate=0)


def run_stock(primary, stock, *, stock_fees=None, dividends=None, buy=(0,), exit=(1,), take_profit=False):
    return runner.run_bank_kdj_backtest(
        primary, stock, signals(primary, buy, exit),
        pd.Series(0.0, index=primary["date"].dt.normalize()), initial_cash=100_000,
        fees=free_fees(), bank_code=STOCK, bank_fees=stock_fees or free_fees(),
        dividends=dividends, bank_take_profit=take_profit,
    )


def test_disabled_stock_take_profit_holds_until_primary_entry():
    primary, stock = bars([10.0] * 4), bars([5.0, 5.0, 6.0, 5.8])
    result = run_stock(primary, stock, buy=(0, 3))

    assert result.nav["bank_quantity"].tolist() == [0, 20_000, 20_000, 0]
    trade = result.trades.iloc[-1]
    assert trade["code"] == STOCK
    assert trade["sell_reason"] == "amv_buy_signal_rotate_back"
    assert trade["pnl_pct"] == pytest.approx(16)
    assert result.open_position["code"] == runner.PRIMARY


def test_stock_defaults_to_eight_percent_price_take_profit():
    primary, stock = bars([10.0] * 3), bars([5.0, 5.0, 5.4])
    result = run_stock(primary, stock, take_profit=None)

    assert result.open_position is None
    assert result.final_value == pytest.approx(108_000)
    assert result.trades.iloc[-1]["sell_reason"] == "bank_take_profit_8pct"


def test_stock_uses_separate_fees_and_affordable_whole_lots():
    primary, stock = bars([10.0] * 3), bars([5.0] * 3)
    fees = FeeConfig.stock_legacy()
    result = run_stock(primary, stock, stock_fees=fees, buy=(0, 2))

    quantity = 19_900
    _, cost = calc_buy_cost(5.0, quantity, fees)
    _, proceeds = calc_sell_proceeds(5.0, quantity, fees)
    trade = result.trades.iloc[-1]
    assert trade["code"] == STOCK
    assert trade["buy_quantity"] == quantity
    assert trade["buy_cost"] == pytest.approx(cost)
    assert trade["sell_proceeds"] == pytest.approx(proceeds)
    assert trade["sell_stamp_duty"] == pytest.approx(5 * .999 * quantity * .001)
    assert trade["pnl"] == pytest.approx(proceeds - cost)
    assert result.final_value == pytest.approx(100_000 - cost + proceeds)
    assert result.trades.iloc[0]["pnl"] == 0
    assert (result.nav["cash"] >= 0).all()


def test_stock_does_not_receive_bank_etf_split():
    dates = ["2025-07-03", "2025-07-04", "2025-07-07", "2025-07-08"]
    result = run_stock(bars([10.0] * 4, dates), bars([5.0] * 4, dates))

    assert result.nav["bank_quantity"].tolist() == [0, 20_000, 20_000, 20_000]
    assert result.final_value == 100_000
    assert result.open_position["reference_price"] == 5


@pytest.mark.parametrize("next_buy,expected_dividend", [(2, 10_000), (3, 10_000)])
def test_dividend_entitlement_credits_cash_and_trade_pnl_once(next_buy, expected_dividend):
    primary, stock = bars([10.0] * 4), bars([5.0, 5.0, 4.5, 4.5])
    ex_date = primary.loc[2, "date"].normalize()
    result = run_stock(primary, stock, buy=(0, next_buy), dividends={ex_date: .5})

    trade = result.trades.loc[result.trades["code"] == STOCK].iloc[0]
    assert trade["dividend_income"] == expected_dividend
    assert trade["pnl"] == pytest.approx(0)
    assert result.nav["dividend_income"].tolist() == [0, 0, expected_dividend, expected_dividend]
    assert result.nav["nav"].tolist() == pytest.approx([100_000] * 4)
    assert result.open_position["quantity"] == 10_000


def test_stock_bought_on_ex_date_has_no_dividend_entitlement():
    primary, stock = bars([10.0] * 3), bars([5.0, 4.5, 4.5])
    result = run_stock(primary, stock, dividends={primary.loc[1, "date"].normalize(): .5})

    assert result.nav["dividend_income"].sum() == 0
    assert result.open_position["dividend_income"] == 0


def test_stock_sold_before_ex_date_has_no_dividend_entitlement():
    primary, stock = bars([10.0] * 4), bars([5.0, 5.0, 5.0, 4.5])
    result = run_stock(primary, stock, buy=(0, 2), dividends={primary.loc[3, "date"].normalize(): .5})

    assert result.nav["dividend_income"].sum() == 0
    assert result.trades.loc[result.trades["code"] == STOCK, "dividend_income"].iloc[0] == 0


def test_optional_stock_take_profit_rounds_target_up_to_cent():
    primary, stock = bars([10.0] * 4), bars([5.03] * 4)
    target = math.ceil(5.03 * 1.08 * 100 - 1e-10) / 100
    stock.loc[2, "high"] = target - .01
    stock.loc[3, "high"] = target
    result = run_stock(primary, stock, take_profit=True)

    trade = result.trades.iloc[-1]
    assert trade["code"] == STOCK
    assert trade["sell_date"] == "20240105"
    assert trade["sell_signal_price"] == pytest.approx(target)
    assert trade["sell_reason"] == "bank_take_profit_8pct"


def test_cash_dividend_adjustment_removes_mechanical_weekly_j_drop():
    dates = pd.bdate_range("2023-01-02", periods=70)
    daily = pd.DataFrame({"date": dates, "high": 11.0, "low": 9.0, "close": 10.0})
    raw = daily.copy()
    raw.loc[60:, ["high", "low", "close"]] *= .8
    expected = compute_dynamic_weekly_kdj(daily)
    actual = compute_dynamic_weekly_kdj(raw, cash_dividends={dates[60]: 2.0})

    pd.testing.assert_frame_equal(actual, expected)
    unadjusted = compute_dynamic_weekly_kdj(raw)
    assert unadjusted.iloc[60]["J"] < actual.iloc[60]["J"]


def test_future_dividend_and_future_prices_do_not_change_prior_weekly_j():
    dates = pd.bdate_range("2023-01-02", periods=70)
    daily = pd.DataFrame({"date": dates, "high": 11.0, "low": 9.0, "close": 10.0})
    dividend = {dates[60]: 2.0}
    full = compute_dynamic_weekly_kdj(daily, cash_dividends=dividend)
    prefix = compute_dynamic_weekly_kdj(daily.iloc[:60], cash_dividends=dividend)

    pd.testing.assert_frame_equal(full.iloc[:60], prefix)


def test_stock_missing_required_day_fails_instead_of_dropping_calendar():
    primary, stock = bars([10.0] * 3), bars([5.0] * 3)
    with pytest.raises(ValueError, match="601288.*20240104"):
        run_stock(primary, stock.iloc[:2])


def write_stock_day(root, date, price, code=STOCK):
    # Same raw-price/volume layout as the sibling strategy's parquet inputs.
    date = pd.Timestamp(date)
    times = list(pd.date_range(date + pd.Timedelta(hours=9, minutes=35), periods=24, freq="5min"))
    times += list(pd.date_range(date + pd.Timedelta(hours=13, minutes=5), periods=24, freq="5min"))
    frame = pd.DataFrame({"trade_time": times, "code": code, "open": price,
                          "high": price, "low": price, "close": price,
                          "vol": 100_000.0, "amount": price * 100_000})
    path = root / str(date.year) / f"{date:%Y%m%d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def test_stock_loader_keeps_pre_start_history_and_ignores_future_files(tmp_path):
    from python.strategies.amv_winning.bank_stock import load_stock_history

    write_stock_day(tmp_path, "2023-12-29", 5.0)
    write_stock_day(tmp_path, "2024-01-02", 5.2)
    write_stock_day(tmp_path, "2024-01-03", 999.0)
    frame, audit = load_stock_history(tmp_path, pd.Timestamp("2024-01-02"))

    assert set(frame["date"].dt.normalize()) == {pd.Timestamp("2023-12-29"), pd.Timestamp("2024-01-02")}
    assert len(frame) == 96
    assert audit["code"] == STOCK
    assert audit["price_basis"] == "raw_verified_with_amount_per_share"


def test_stock_loader_rejects_adjusted_execution_prices(tmp_path):
    from python.strategies.amv_winning.bank_stock import load_stock_history

    path = write_stock_day(tmp_path, "2024-01-02", 5.0)
    frame = pd.read_parquet(path)
    frame[["open", "high", "low", "close"]] *= .8
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="复权"):
        load_stock_history(tmp_path, pd.Timestamp("2024-01-02"))


def test_stock_runner_uses_own_j_and_writes_actual_asset_fees_and_inputs(tmp_path):
    dates = pd.date_range("2024-01-01", periods=14)
    primary = bars([10.0] * 14, list(dates))
    amv = pd.DataFrame({"date": dates, "close": [100.0] * 10 + [104.1, 90.0, 90.0, 90.0]})
    history = list(pd.date_range(end="2023-12-29", periods=13, freq="W-FRI"))
    prices = [12.0] * 8 + [10.0, 9.0, 8.0, 7.0, 6.0] + [5.0] * 14
    stock_dir = tmp_path / "stock"
    for date, price in zip(history + list(dates), prices, strict=True):
        write_stock_day(stock_dir, date, price)
    amv_path, primary_path = tmp_path / "amv.csv", tmp_path / "primary.csv"
    amv.to_csv(amv_path, index=False)
    primary.to_csv(primary_path, index=False)
    dividends = tmp_path / "dividends.csv"
    dividends.write_text("ex_date,cash_per_share,source\n2024-01-14,0.5,https://example.test/announcement\n")
    output = tmp_path / "run"

    metrics = runner.run_research(
        amv_path, primary_path, output, output / "report.md", initial_cash=100_000,
        start_date="20240110", end_date="20240114", fees=free_fees(),
        bank_code=STOCK, stock_data_dir=stock_dir, stock_dividends_path=dividends,
        bank_fees=free_fees(), bank_path=tmp_path / "bank_etf_not_required.csv",
        bank_take_profit=False,
    )

    assert metrics["parameters"]["bank_code"] == STOCK
    assert metrics["parameters"]["bank_take_profit_pct"] is None
    assert metrics["parameters"]["bank_split_ratio"] is None
    assert metrics["bank"]["dividend_income"] == 10_000
    assert metrics["final_nav"] == 110_000
    assert metrics["original_strategy"]["final_nav"] == 100_000
    nav = pd.read_csv(output / "nav.csv")
    assert nav.loc[2:, "position_code"].tolist() == [STOCK] * 3
    assert metrics["bank_fees"]["stamp_duty_rate"] == 0
    assert "农业银行" in (output / "report.md").read_text()
    assert (output / "inputs" / "601288.SH.csv").exists()
    assert (output / "inputs" / "dividends_601288.csv").exists()
    source_manifest = json.loads((output / "source_manifest.json").read_text())
    assert source_manifest["stock"]["code"] == STOCK
    assert "inputs/601288.SH.csv" in source_manifest["sha256"]


def test_registry_default_uses_stock_data_and_passes_no_take_profit(tmp_path, monkeypatch):
    import yaml
    from python import task_registry
    from python.run_backtest import RunRequest

    config = tmp_path / "config.yaml"
    paths = {"amv_csv": str(tmp_path / "amv.csv"), "primary_csv": str(tmp_path / "primary.csv"),
             "stock_5m_dir": str(tmp_path / "stocks"), "stock_dividends_csv": str(tmp_path / "dividends.csv")}
    for key, path in paths.items():
        if key == "stock_5m_dir":
            Path(path).mkdir()
        else:
            Path(path).touch()
    config.write_text(yaml.safe_dump({"paths": paths, "bank_take_profit": False}))
    received = {}
    monkeypatch.setattr(runner, "run_research", lambda *args, **kwargs: received.update(kwargs))
    request = RunRequest("amv_winning", "strategy", "20200101", "20251231", tmp_path / "run",
                         free_fees(), "legacy_same_close_idealized", config)

    task_registry._run_amv_winning(request)

    assert received["bank_code"] == STOCK
    assert received["bank_take_profit"] is False
    assert received["stock_data_dir"] == Path(paths["stock_5m_dir"])
    spec = task_registry.TASKS[("strategy", "amv_winning")]
    assert spec.default_config.name == "config.yaml"
    assert "stock_5m_dir" in spec.source_path_keys
    assert not any(path.name == "512800.SH.csv" for path in spec.data_sources)
    assert yaml.safe_load(spec.default_config.read_text())["bank_take_profit"] is True


@pytest.mark.parametrize("column,value", [("close", float("nan")), ("open", float("inf")),
                                          ("high", 0.0), ("high", 4.0)])
def test_stock_loader_rejects_missing_or_invalid_ohlc(tmp_path, column, value):
    from python.strategies.amv_winning.bank_stock import load_stock_history

    path = write_stock_day(tmp_path, "2024-01-02", 5.0)
    frame = pd.read_parquet(path)
    frame.loc[frame.index[-1], column] = value
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="OHLC"):
        load_stock_history(tmp_path, pd.Timestamp("2024-01-02"))


def test_stock_loader_corrects_verified_20240403_volume_scale_without_changing_prices(tmp_path):
    from python.strategies.amv_winning.bank_stock import load_stock_history

    path = write_stock_day(tmp_path, "2024-04-03", 4.27)
    frame = pd.read_parquet(path)
    frame["vol"] *= 100
    frame.to_parquet(path, index=False)
    actual, audit = load_stock_history(tmp_path, pd.Timestamp("2024-04-03"))

    assert actual["close"].tolist() == pytest.approx([4.27] * 48)
    assert actual["volume"].tolist() == pytest.approx([100_000] * 48)
    assert audit["volume_corrections"] == {"20240403": {"divisor": 100, "reason": "verified_amount_per_share"}}


def test_input_snapshot_preserves_float32_price_exactly_for_replay(tmp_path):
    from python.strategies.amv_winning.bank_stock import snapshot_stock_inputs

    frame = bars([5.03]).astype({"open": "float32", "high": "float32", "low": "float32", "close": "float32"})
    dividend_path = tmp_path / "dividends.csv"
    dividend_path.write_text("ex_date,cash_per_share,source\n")
    amv_path, primary_path = tmp_path / "amv.csv", tmp_path / "primary.csv"
    amv_path.write_text("date,close\n")
    primary_path.write_text("date,close\n")
    snapshot_stock_inputs(tmp_path, frame, dividend_path, {}, amv_path=amv_path, primary_path=primary_path)

    restored = pd.read_csv(tmp_path / "inputs/601288.SH.csv", float_precision="round_trip")
    assert restored.loc[0, "close"] == float(frame.loc[0, "close"])
