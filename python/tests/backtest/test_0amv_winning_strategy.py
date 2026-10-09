from __future__ import annotations

import pandas as pd
import pytest

from python.backtest.broker import FeeConfig
from python.strategies.amv_winning.runner import (
    compute_performance_metrics,
    generate_amv_signals,
    run_research,
    run_full_position_backtest,
)


def test_generate_amv_signals_accepts_compounded_two_day_gain_and_ma5() -> None:
    dates = pd.date_range("2024-01-01", periods=32, freq="D")
    closes = [100.0] * 30 + [103.0, 104.03]
    amv = pd.DataFrame({"date": dates, "close": closes})

    signals = generate_amv_signals(amv)

    row = signals.iloc[-1]
    assert bool(row["buy_signal"])
    assert row["two_day_return"] > 0.04
    assert row["close"] >= row["ma5"]


def test_generate_amv_signals_requires_current_close_at_or_above_ma5() -> None:
    dates = pd.date_range("2024-01-01", periods=7, freq="D")
    closes = [100.0, 100.0, 110.0, 110.0, 110.0, 100.0, 104.0]
    amv = pd.DataFrame({"date": dates, "close": closes})

    signals = generate_amv_signals(amv)

    assert not bool(signals.iloc[-1]["buy_signal"])


def test_generate_amv_signals_marks_ma10_break_and_only_macd_cross_day() -> None:
    dates = pd.date_range("2024-01-01", periods=50, freq="D")
    closes = [100.0] * 20 + list(range(101, 111)) + [110.0] * 5 + [108.0, 105.0, 102.0, 99.0, 96.0] + [96.0] * 10
    amv = pd.DataFrame({"date": dates, "close": closes})

    signals = generate_amv_signals(amv)

    death_crosses = signals.index[signals["exit_macd"]].tolist()
    assert len(death_crosses) == 1
    cross_index = death_crosses[0]
    assert signals.loc[cross_index - 1, "dif"] >= signals.loc[cross_index - 1, "dea"]
    assert signals.loc[cross_index, "dif"] < signals.loc[cross_index, "dea"]
    assert signals["exit_ma10"].any()


def _signals(dates: list[str], buys: set[str] | None = None, exits: set[str] | None = None) -> pd.DataFrame:
    buys = buys or set()
    exits = exits or set()
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "buy_signal": [date in buys for date in dates],
        "exit_ma10": [date in exits for date in dates],
        "exit_macd": False,
    })


def _bars(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).assign(volume=1_000_000)


def test_backtest_buys_close_and_hard_stops_from_next_bar() -> None:
    bars = _bars([
        ("2024-01-02 15:00", 10.0, 10.1, 9.9, 10.0),
        ("2024-01-03 10:30", 10.0, 10.1, 9.7, 9.8),
    ])
    signals = _signals(["2024-01-02", "2024-01-03"], buys={"2024-01-02"})

    result = run_full_position_backtest(bars, signals, initial_cash=100_000.0)

    trade = result.trades.iloc[0]
    assert trade["buy_signal_price"] == 10.0
    assert trade["buy_exec_price"] == pytest.approx(10.01)
    assert trade["sell_reason"] == "hard_stop_2.5pct"
    assert trade["sell_signal_price"] == pytest.approx(10.01 * 0.975)
    assert trade["sell_exec_price"] == pytest.approx(10.01 * 0.975 * 0.999)
    assert {"cash", "position_quantity"}.issubset(result.nav.columns)
    assert (result.nav["cash"] >= 0).all()


def test_profit_trail_arms_after_five_percent_and_starts_next_session() -> None:
    bars = _bars([
        ("2024-01-02 15:00", 10.0, 10.1, 9.9, 10.0),
        ("2024-01-03 10:30", 10.3, 10.6, 10.3, 10.5),
        ("2024-01-03 15:00", 10.5, 10.6, 10.3, 10.4),
        ("2024-01-04 10:30", 10.4, 10.5, 10.2, 10.25),
    ])
    signals = _signals(["2024-01-02", "2024-01-03", "2024-01-04"], buys={"2024-01-02"})

    result = run_full_position_backtest(bars, signals, initial_cash=100_000.0)

    trade = result.trades.iloc[0]
    assert trade["sell_date"] == "20240104"
    assert trade["sell_reason"] == "profit_trail_body_break_5pct"
    assert trade["sell_signal_price"] == 10.3


def test_share_consolidation_keeps_position_value_continuous() -> None:
    ratio = 0.36555
    bars = _bars([
        ("2022-09-01 15:00", 1.0, 1.0, 1.0, 1.0),
        ("2022-09-05 10:30", 1.0 / ratio, 1.0 / ratio, 1.0 / ratio, 1.0 / ratio),
        ("2022-09-05 15:00", 1.0 / ratio, 1.0 / ratio, 1.0 / ratio, 1.0 / ratio),
    ])
    signals = _signals(["2022-09-01", "2022-09-05"], buys={"2022-09-01"})

    result = run_full_position_backtest(bars, signals, initial_cash=100_000.0)

    assert result.trades.empty
    assert result.open_position is not None
    assert result.open_position["quantity"] == 36_482
    assert result.nav.iloc[-1]["nav"] == pytest.approx(result.nav.iloc[0]["nav"], rel=0.001)


def test_share_consolidation_ignores_suspended_zero_volume_session() -> None:
    ratio = 0.36555
    bars = _bars([
        ("2022-09-01 15:00", 1.0, 1.0, 1.0, 1.0),
        ("2022-09-02 10:30", 0.982, 0.982, 0.982, 0.982),
        ("2022-09-02 15:00", 0.982, 0.982, 0.982, 0.982),
        ("2022-09-05 10:30", 1.0 / ratio, 1.0 / ratio, 1.0 / ratio, 1.0 / ratio),
        ("2022-09-05 15:00", 1.0 / ratio, 1.0 / ratio, 1.0 / ratio, 1.0 / ratio),
    ])
    bars.loc[bars["date"].str.startswith("2022-09-02"), "volume"] = 0
    signals = _signals(["2022-09-01", "2022-09-02", "2022-09-05"], buys={"2022-09-01"})

    result = run_full_position_backtest(bars, signals, initial_cash=100_000.0)

    assert result.trades.empty
    assert result.open_position is not None
    assert result.nav["date"].tolist() == [pd.Timestamp("2022-09-01"), pd.Timestamp("2022-09-05")]


def test_close_exit_has_priority_over_same_day_buy_signal() -> None:
    bars = _bars([
        ("2024-01-02 15:00", 10.0, 10.0, 10.0, 10.0),
        ("2024-01-03 15:00", 10.5, 10.5, 10.5, 10.5),
    ])
    signals = _signals(
        ["2024-01-02", "2024-01-03"],
        buys={"2024-01-02", "2024-01-03"},
        exits={"2024-01-03"},
    )

    result = run_full_position_backtest(bars, signals, initial_cash=100_000.0)

    assert len(result.trades) == 1
    assert result.trades.iloc[0]["sell_reason"] == "amv_close_below_ma10"
    assert result.open_position is None


def test_metrics_use_calendar_span_and_report_drawdown_and_win_rate() -> None:
    nav = pd.DataFrame({
        "date": pd.to_datetime(["2023-01-01", "2023-07-01", "2024-01-01"]),
        "nav": [100_000.0, 90_000.0, 121_000.0],
        "invested": [False, True, False],
    })
    trades = pd.DataFrame({"pnl": [10_000.0, -5_000.0], "pnl_pct": [10.0, -5.0]})

    metrics = compute_performance_metrics(nav, trades, 100_000.0, has_open_position=False)

    assert metrics["total_return_pct"] == pytest.approx(21.0)
    assert metrics["annualized_return_pct"] == pytest.approx(21.0, abs=0.1)
    assert metrics["max_drawdown_pct"] == pytest.approx(-10.0)
    assert metrics["win_rate_pct"] == 50.0
    assert metrics["exposure_pct"] == pytest.approx(100 / 3)


def test_metrics_include_first_day_cost_against_initial_capital() -> None:
    nav = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
        "nav": [99_000.0, 100_000.0],
        "invested": [True, True],
    })

    metrics = compute_performance_metrics(nav, pd.DataFrame(), 100_000.0, has_open_position=True)

    assert metrics["max_drawdown_pct"] == pytest.approx(-1.0)


def test_run_research_writes_reproducible_artifacts(tmp_path) -> None:
    dates = pd.date_range("2024-01-01", periods=12, freq="D")
    amv = pd.DataFrame({"date": dates, "close": [100.0] * 10 + [104.1, 90.0]})
    etf = pd.DataFrame({
        "时间": dates + pd.Timedelta(hours=15),
        "开盘价": [10.0] * 12,
        "最高价": [10.1] * 12,
        "最低价": [9.9] * 12,
        "收盘价": [10.0] * 11 + [10.2],
        "成交量": [1_000_000] * 12,
    })
    amv_path = tmp_path / "amv.csv"
    etf_path = tmp_path / "etf.csv"
    bank_path = tmp_path / "bank.csv"
    output_dir = tmp_path / "run"
    report_path = tmp_path / "report.md"
    amv.to_csv(amv_path, index=False)
    etf.to_csv(etf_path, index=False)
    etf.to_csv(bank_path, index=False)

    metrics = run_research(amv_path, etf_path, output_dir, report_path, initial_cash=100_000.0,
                           bank_path=bank_path)

    assert metrics["closed_trade_count"] == 1
    assert (output_dir / "metrics.json").exists()
    assert (output_dir / "trades.csv").exists()
    assert (output_dir / "nav.csv").exists()
    assert (output_dir / "annual_returns.csv").exists()
    assert "信号日收盘成交" in report_path.read_text(encoding="utf-8")
    assert "买入持有基准" in report_path.read_text(encoding="utf-8")

    narrowed = tmp_path / "narrowed"
    fee_free = FeeConfig.etf_legacy().with_overrides(
        commission_rate=0.0, min_commission=0.0, slippage_rate=0.0,
    )
    run_research(amv_path, etf_path, narrowed, narrowed / "report.md",
                 initial_cash=100_000.0, start_date="20240110", end_date="20240112", fees=fee_free,
                 bank_path=bank_path)
    narrowed_nav = pd.read_csv(narrowed / "nav.csv")
    narrowed_trades = pd.read_csv(narrowed / "trades.csv")
    assert narrowed_nav["date"].min().startswith("2024-01-10")
    assert narrowed_trades.iloc[0]["buy_exec_price"] == 10.0
