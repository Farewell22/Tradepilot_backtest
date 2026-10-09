from __future__ import annotations

import pandas as pd
import pytest
import json

from python.backtest.broker import FeeConfig
from python.strategies.amv_winning import runner


PRIMARY = "512100.SH"
BANK = "512800.SH"


def _bars(prices, dates=None) -> pd.DataFrame:
    dates = pd.to_datetime(dates) if dates else pd.bdate_range("2024-01-02", periods=len(prices))
    return pd.DataFrame({"date": dates + pd.Timedelta(hours=15), "open": prices,
                         "high": prices, "low": prices, "close": prices, "volume": 1_000_000})


def _signals(bars, buys=(), exits=(), macd=()) -> pd.DataFrame:
    return pd.DataFrame({"date": bars["date"].dt.normalize(),
                         "buy_signal": [i in buys for i in range(len(bars))],
                         "exit_ma10": [i in exits for i in range(len(bars))],
                         "exit_macd": [i in macd for i in range(len(bars))]})


def _fees() -> FeeConfig:
    return FeeConfig.etf_legacy().with_overrides(commission_rate=0, min_commission=0, slippage_rate=0)


def _run(primary, bank, signals, j=None, fees=None, cash=100_000, bank_take_profit=True):
    assert hasattr(runner, "run_bank_kdj_backtest"), "缺少银行 ETF 条件买入策略"
    weekly_j = pd.Series(j if j is not None else [0.0] * len(primary),
                         index=primary["date"].dt.normalize(), name="J")
    return runner.run_bank_kdj_backtest(primary, bank, signals, weekly_j,
                                        initial_cash=cash, fees=fees or _fees(),
                                        bank_take_profit=bank_take_profit)


def test_initial_cash_does_not_buy_bank_before_first_primary_exit() -> None:
    primary, bank = _bars([10.0] * 3), _bars([5.0] * 3)
    result = _run(primary, bank, _signals(primary))

    assert result.trades.empty
    assert result.open_position is None
    assert result.nav["bank_quantity"].tolist() == [0, 0, 0]
    assert result.final_value == 100_000
    assert "sell_reason" in result.trades.columns


def test_bank_entry_requires_strictly_below_ten() -> None:
    primary, bank = _bars([10.0] * 4), _bars([5.0] * 4)
    result = _run(primary, bank, _signals(primary, buys=(0,), exits=(1,)), [0, 10, 9, 99])

    assert result.nav["bank_quantity"].tolist() == [0, 0, 20_000, 20_000]
    assert result.open_position["code"] == BANK


@pytest.mark.parametrize("exit_kind", ["ma10", "macd", "hard_stop", "profit_trail"])
def test_every_primary_sell_starts_bank_observation(exit_kind) -> None:
    primary, bank = _bars([10.0] * 4), _bars([5.0] * 4)
    signals = _signals(primary, buys=(0,), exits=(1,) if exit_kind == "ma10" else (),
                       macd=(1,) if exit_kind == "macd" else ())
    if exit_kind == "hard_stop":
        primary.loc[1, "low"] = 9.7
    if exit_kind == "profit_trail":
        primary.loc[1, ["open", "high", "low", "close"]] = [10.3, 10.6, 10.3, 10.4]
        primary.loc[2, ["open", "high", "low", "close"]] = [10.4, 10.5, 10.2, 10.25]

    result = _run(primary, bank, signals)

    assert result.open_position["code"] == BANK
    assert result.nav.iloc[-1]["bank_quantity"] > 0
    assert result.nav.iloc[-1]["position_quantity"] == 0


def test_bank_has_no_stop_and_rotates_back_on_primary_entry() -> None:
    primary, bank = _bars([10.0] * 4), _bars([5.0, 5.0, 4.0, 4.0])
    result = _run(primary, bank, _signals(primary, buys=(0, 3), exits=(1, 2)), [99, 0, 99, 0])

    assert result.nav["bank_quantity"].tolist() == [0, 20_000, 20_000, 0]
    trade = result.trades.iloc[-1]
    assert trade["code"] == BANK
    assert trade["sell_reason"] == "amv_buy_signal_rotate_back"
    assert trade["pnl_pct"] == pytest.approx(-20.0)
    assert result.open_position["code"] == PRIMARY
    assert result.open_position["quantity"] == 8_000
    assert (result.nav["cash"] >= 0).all()


def test_primary_entry_wins_over_bank_entry_after_intraday_stop() -> None:
    primary, bank = _bars([10.0, 9.8]), _bars([5.0, 5.0])
    primary.loc[1, "low"] = 9.7
    result = _run(primary, bank, _signals(primary, buys=(0, 1)))

    assert result.open_position["code"] == PRIMARY
    assert result.nav["bank_quantity"].tolist() == [0, 0]


def test_close_exit_still_wins_over_conflicting_primary_buy() -> None:
    primary, bank = _bars([10.0] * 2), _bars([5.0] * 2)
    result = _run(primary, bank, _signals(primary, buys=(0, 1), exits=(1,)))

    assert result.trades.iloc[0]["sell_reason"] == "amv_close_below_ma10"
    assert result.open_position["code"] == BANK


@pytest.mark.parametrize("open_price,high_price,expected_price", [(5.1, 5.4, 5.4), (5.6, 5.7, 5.6)])
def test_bank_take_profit_waits_until_next_close_to_reenter(open_price, high_price, expected_price) -> None:
    primary, bank = _bars([10.0] * 4), _bars([5.0] * 4)
    bank.loc[2, ["open", "high", "low", "close"]] = [open_price, high_price, 5.0, 5.1]
    result = _run(primary, bank, _signals(primary, buys=(0,), exits=(1,)))

    trade = result.trades.iloc[-1]
    assert trade["sell_reason"] == "bank_take_profit_8pct"
    assert trade["sell_signal_price"] == pytest.approx(expected_price)
    assert result.nav.loc[2, "bank_quantity"] == 0
    assert result.nav.loc[2, "cash"] == pytest.approx(20_000 * expected_price)
    assert result.nav.loc[3, "bank_quantity"] > 0


def test_primary_entry_on_bank_take_profit_day_uses_sale_cash() -> None:
    primary, bank = _bars([10.0] * 3), _bars([5.0] * 3)
    bank.loc[2, "high"] = 5.4
    result = _run(primary, bank, _signals(primary, buys=(0, 2), exits=(1,)))

    assert result.open_position["code"] == PRIMARY
    assert result.open_position["quantity"] == 10_800
    assert result.nav.iloc[-1]["bank_quantity"] == 0


def test_disabled_bank_take_profit_holds_until_primary_entry() -> None:
    primary, bank = _bars([10.0] * 4), _bars([5.0, 5.0, 5.5, 5.8])
    result = _run(primary, bank, _signals(primary, buys=(0, 3), exits=(1,)), bank_take_profit=False)

    trade = result.trades.iloc[-1]
    assert trade["code"] == BANK
    assert trade["sell_date"] == "20240105"
    assert trade["sell_reason"] == "amv_buy_signal_rotate_back"
    assert trade["pnl_pct"] == pytest.approx(16.0)
    assert result.nav.loc[2, "bank_quantity"] == 20_000
    assert result.open_position["code"] == PRIMARY
    assert result.open_position["quantity"] == 11_600


def test_take_profit_uses_buy_execution_price_and_net_pnl_includes_fees() -> None:
    primary, bank = _bars([10.0] * 4), _bars([5.0] * 4)
    bank.loc[2, "high"] = 5.4
    bank.loc[3, "high"] = 5.406
    result = _run(primary, bank, _signals(primary, buys=(0,), exits=(1,)), fees=FeeConfig.etf_legacy())

    bank_trade = result.trades.iloc[-1]
    assert bank_trade["sell_date"] == "20240105"
    assert bank_trade["sell_signal_price"] == pytest.approx(5.005 * 1.08)
    assert bank_trade["pnl_pct"] < 8
    assert result.nav.loc[2, "bank_quantity"] > 0


def test_bank_split_preserves_nav_and_adjusts_take_profit_target() -> None:
    dates = ["2025-07-03", "2025-07-04", "2025-07-07", "2025-07-08"]
    primary, bank = _bars([10.0] * 4, dates), _bars([10.0, 10.0, 5.0, 5.0], dates)
    bank.loc[3, "high"] = 5.4
    result = _run(primary, bank, _signals(primary, buys=(0,), exits=(1,)))

    assert result.nav.loc[1, "bank_quantity"] == 10_000
    assert result.nav.loc[2, "bank_quantity"] == 20_000
    assert result.nav.loc[2, "nav"] == 100_000
    assert result.trades.iloc[-1]["sell_quantity"] == 20_000
    assert result.trades.iloc[-1]["sell_signal_price"] == pytest.approx(5.4)
    assert result.final_value == pytest.approx(108_000)


def test_without_bank_entry_all_legacy_trades_and_nav_are_identical() -> None:
    primary, bank = _bars([10.0, 10.0, 9.8, 10.0]), _bars([5.0] * 4)
    primary.loc[2, "low"] = 9.7
    signals = _signals(primary, buys=(0, 3))
    original = runner.run_full_position_backtest(primary, signals, initial_cash=100_000, fees=_fees())
    result = _run(primary, bank, signals, [50] * 4)

    pd.testing.assert_frame_equal(result.nav[original.nav.columns], original.nav)
    pd.testing.assert_frame_equal(result.trades[original.trades.columns], original.trades)


def test_missing_bank_session_is_rejected() -> None:
    primary, bank = _bars([10.0] * 2), _bars([5.0] * 2)
    with pytest.raises(ValueError, match="银行.*20240103"):
        _run(primary, bank.iloc[:1], _signals(primary, buys=(0,), exits=(1,)))


def test_cash_below_one_lot_remains_cash() -> None:
    primary, bank = _bars([10.0] * 2), _bars([5.0] * 2)
    result = _run(primary, bank, _signals(primary, buys=(0,), exits=(1,)), cash=50)

    assert result.final_value == 50
    assert result.open_position is None


def test_runner_uses_pre_start_weekly_history_and_writes_both_baselines(tmp_path) -> None:
    dates = pd.date_range("2024-01-01", periods=14)
    primary = _bars([10.0] * 14, list(dates))
    amv = pd.DataFrame({"date": dates, "close": [100.0] * 10 + [104.1, 90.0, 90.0, 90.0]})
    earlier = list(pd.date_range(end="2023-12-29", periods=13, freq="W-FRI"))
    bank = _bars([12.0] * 8 + [10.0, 9.0, 8.0, 7.0, 6.0] + [5.0] * 14, earlier + list(dates))
    bank.loc[25, "high"] = 5.4
    amv_path, primary_path, bank_path = (tmp_path / name for name in ("amv.csv", "primary.csv", "bank.csv"))
    for frame, path in ((amv, amv_path), (primary, primary_path), (bank, bank_path)):
        frame.to_csv(path, index=False)
    output = tmp_path / "result"

    metrics = runner.run_research(amv_path, primary_path, output, output / "report.md",
                                  initial_cash=100_000, start_date="20240110", end_date="20240114",
                                  fees=_fees(), bank_path=bank_path)

    nav = pd.read_csv(output / "nav.csv")
    trades = pd.read_csv(output / "trades.csv")
    assert nav.loc[nav["date"].str.startswith("2024-01-12"), "bank_quantity"].iloc[0] == 20_000
    assert nav.loc[nav["date"].str.startswith("2024-01-13"), "bank_quantity"].iloc[0] == 0
    assert nav.loc[nav["date"].str.startswith("2024-01-14"), "bank_quantity"].iloc[0] == 21_600
    assert trades["code"].tolist() == [PRIMARY, BANK]
    assert metrics["original_strategy"]["final_nav"] == 100_000
    assert metrics["final_nav"] == 108_000
    assert metrics["bank"]["closed_trade_count"] == 1
    assert json.loads((output / "metrics.json").read_text())["open_position"]["code"] == BANK
    assert (output / "original_nav.csv").exists()
    assert (output / "original_trades.csv").exists()
    assert (output / "bank_weekly_kdj.csv").exists()
    assert "纯现金" in (output / "report.md").read_text()


def test_registry_requires_agricultural_bank_data(tmp_path) -> None:
    from python import task_registry
    from python.run_backtest import RunRequest

    data_dir, etf_dir = tmp_path / "data", tmp_path / "etfs"
    data_dir.mkdir()
    etf_dir.mkdir()
    (data_dir / "0AMV-260612.csv").write_text("date,close\n")
    (etf_dir / "512100.SH.csv").write_text("date,close\n")
    config = tmp_path / "config.yaml"
    config.write_text(
        f"paths:\n  amv_csv: {data_dir / '0AMV-260612.csv'}\n"
        f"  primary_csv: {etf_dir / '512100.SH.csv'}\n"
        f"  stock_5m_dir: {data_dir / '5m_price'}\n"
        f"  stock_dividends_csv: {data_dir / 'dividends.csv'}\n"
    )
    request = RunRequest("amv_winning", "strategy", "20200101", "20251231", tmp_path / "run",
                         _fees(), "legacy_same_close_idealized", config)

    with pytest.raises(FileNotFoundError, match="5m_price"):
        task_registry._run_amv_winning(request)

    sources = task_registry.TASKS[("strategy", "amv_winning")].data_sources
    assert any(path.name == "5m_price" for path in sources)


def test_runner_disabled_bank_take_profit_reports_actual_rules(tmp_path) -> None:
    dates = pd.date_range("2024-01-01", periods=14)
    primary = _bars([10.0] * 14, list(dates))
    amv = pd.DataFrame({"date": dates, "close": [100.0] * 10 + [104.1, 90.0, 90.0, 90.0]})
    earlier = list(pd.date_range(end="2023-12-29", periods=13, freq="W-FRI"))
    bank = _bars([12.0] * 8 + [10.0, 9.0, 8.0, 7.0, 6.0] + [5.0] * 14, earlier + list(dates))
    bank.loc[25, "high"] = 5.4
    amv_path, primary_path, bank_path = (tmp_path / name for name in ("amv.csv", "primary.csv", "bank.csv"))
    for frame, path in ((amv, amv_path), (primary, primary_path), (bank, bank_path)):
        frame.to_csv(path, index=False)
    output = tmp_path / "result"

    metrics = runner.run_research(amv_path, primary_path, output, output / "report.md",
                                  initial_cash=100_000, start_date="20240110", end_date="20240114",
                                  fees=_fees(), bank_path=bank_path, bank_take_profit=False)

    assert metrics["bank"]["closed_trade_count"] == 0
    assert metrics["parameters"]["bank_take_profit_pct"] is None
    assert metrics["final_nav"] == 100_000
    nav = pd.read_csv(output / "nav.csv")
    assert nav.loc[nav["date"].str.startswith("2024-01-13"), "bank_quantity"].iloc[0] == 20_000
    assert "不设固定止盈" in (output / "report.md").read_text()
