import pandas as pd
import pytest
from python.backtest.broker import FeeConfig

from python.research.amv.ma10_above_ma30_gap.study import (
    BacktestResult,
    _metrics,
    classify_buy_point,
    run_full_position_backtest,
)


def test_classify_buy_point_uses_shallow_pullback_class_1_and_vetoes_p90():
    assert classify_buy_point(0.45, 0.39, ma3_rising=False) == "class_3"
    assert classify_buy_point(0.65, 0.55, ma3_rising=False) == "class_2"
    assert classify_buy_point(0.32, 0.29, ma3_rising=True) == "class_1"
    assert classify_buy_point(0.32, 0.29, ma3_rising=False) is None
    assert classify_buy_point(0.82, 0.79, ma3_rising=True) is None
    assert classify_buy_point(0.91, 0.79, ma3_rising=True) is None


def test_backtest_buys_next_open_and_sells_on_next_open_after_sell_signal():
    etf = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
        "open": [10.0, 10.0, 11.0, 12.0],
        "close": [10.0, 10.5, 11.5, 12.0],
    })
    buys = {pd.Timestamp("2024-01-02"): "class_2"}
    sells = {pd.Timestamp("2024-01-03"): ["sell_1"]}

    result = run_full_position_backtest(etf, buys, sells, initial_cash=10_000.0)

    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade["buy_date"] == "20240102"
    assert trade["sell_date"] == "20240103"
    assert trade["sell_reason"] == "sell_signal_sell_1"
    assert result.final_value > 10_000.0


def test_research_trade_simulation_uses_requested_fees():
    etf = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        "open": [10.0, 10.0, 11.0], "close": [10.0, 10.0, 11.0],
    })
    zero = FeeConfig(commission_rate=0, min_commission=0, stamp_duty_rate=0,
                     transfer_fee_rate=0, slippage_rate=0)
    result = run_full_position_backtest(
        etf, {pd.Timestamp("2024-01-02"): "class_2"},
        {pd.Timestamp("2024-01-03"): ["sell_1"]}, initial_cash=10_000, fees=zero,
    )
    trade = result.trades.iloc[0]
    assert trade["buy_exec_price"] == 10
    assert trade["sell_exec_price"] == 11


def test_sell_signal_has_priority_and_blocks_same_session_reentry():
    etf = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
        "open": [10.0, 10.0, 11.0, 12.0],
        "close": [10.0, 10.5, 11.5, 12.0],
    })
    buys = {pd.Timestamp("2024-01-02"): "class_2", pd.Timestamp("2024-01-03"): "class_1"}
    sells = {pd.Timestamp("2024-01-03"): ["sell_2"]}

    result = run_full_position_backtest(etf, buys, sells, initial_cash=10_000.0)

    assert len(result.trades) == 1
    assert result.trades.iloc[0]["sell_date"] == "20240103"
    assert result.ignored_buy_signals == 1


def test_backtest_applies_five_percent_stop_from_the_day_after_entry():
    etf = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        "open": [10.0, 10.0, 10.0],
        "high": [10.0, 10.2, 10.1],
        "low": [10.0, 9.8, 9.4],
        "close": [10.0, 10.0, 9.6],
    })
    buys = {pd.Timestamp("2024-01-02"): "class_2"}

    result = run_full_position_backtest(etf, buys, {}, initial_cash=10_000.0)

    trade = result.trades.iloc[0]
    assert trade["sell_date"] == "20240103"
    assert trade["sell_reason"] == "stop_loss_5pct"
    assert trade["sell_signal_price"] == pytest.approx(10.0 * 1.001 * 0.95)


def test_trend_exit_blocks_same_session_reentry():
    etf = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        "open": [10.0, 10.0, 11.0],
        "close": [10.0, 10.5, 11.0],
    })
    buys = {pd.Timestamp("2024-01-02"): "class_2", pd.Timestamp("2024-01-03"): "class_1"}
    trend_exits = {pd.Timestamp("2024-01-03"): ["ma10_le_ma30"]}

    result = run_full_position_backtest(etf, buys, {}, trend_exit_schedule=trend_exits, initial_cash=10_000.0)

    assert len(result.trades) == 1
    assert result.trades.iloc[0]["sell_reason"] == "trend_exit_ma10_le_ma30"
    assert result.ignored_buy_signals == 1


def test_metrics_annualizes_return_using_nav_calendar_span():
    result = BacktestResult(
        final_value=242_000.0,
        nav=pd.DataFrame({
            "date": pd.to_datetime(["2023-01-01", "2024-01-01"]),
            "nav": [200_000.0, 242_000.0],
        }),
        trades=pd.DataFrame(),
        ignored_buy_signals=0,
    )

    metrics = _metrics(result)

    assert metrics["annualized_return_pct"] == pytest.approx(21.0)


def test_profit_trail_uses_prior_daily_body_low_after_seven_percent_profit_is_armed():
    etf = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        "open": [10.0, 10.0, 10.6],
        "high": [10.1, 10.8, 10.7],
        "low": [9.9, 9.9, 9.8],
        "close": [10.0, 10.5, 10.2],
    })
    intraday = pd.DataFrame({
        "date": pd.to_datetime([
            "2024-01-02 10:30", "2024-01-02 14:00", "2024-01-03 10:30",
        ]),
        "open": [10.0, 10.5, 10.6],
        "high": [10.6, 10.8, 10.7],
        "low": [9.9, 10.4, 9.8],
        "close": [10.5, 10.5, 10.0],
    })
    buys = {pd.Timestamp("2024-01-02"): "class_2"}

    result = run_full_position_backtest(etf, buys, {}, intraday=intraday, initial_cash=10_000.0)

    trade = result.trades.iloc[0]
    assert trade["sell_date"] == "20240103"
    assert trade["sell_reason"] == "profit_trail_body_break_7pct"
    assert trade["sell_signal_price"] == 10.0


def test_low_momentum_signal_sells_half_of_original_entry_quantity():
    etf = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        "open": [10.0, 10.0, 11.0], "close": [10.0, 10.5, 11.0],
    })
    buys = {pd.Timestamp("2024-01-02"): "class_2"}
    low_momentum_sells = {pd.Timestamp("2024-01-03"): ["sell_1"]}

    result = run_full_position_backtest(
        etf, buys, {}, low_momentum_sell_schedule=low_momentum_sells, initial_cash=10_000.0
    )

    trade = result.trades.iloc[0]
    assert trade["sell_quantity"] == trade["buy_quantity"] // 2
    assert trade["is_partial_exit"]
    assert trade["position_after_quantity"] == trade["buy_quantity"] // 2


def test_two_low_momentum_signals_on_one_day_clear_the_position():
    etf = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        "open": [10.0, 10.0, 11.0], "close": [10.0, 10.5, 11.0],
    })
    buys = {pd.Timestamp("2024-01-02"): "class_2"}
    low_momentum_sells = {pd.Timestamp("2024-01-03"): ["sell_1", "sell_2"]}

    result = run_full_position_backtest(
        etf, buys, {}, low_momentum_sell_schedule=low_momentum_sells, initial_cash=10_000.0
    )

    trade = result.trades.iloc[0]
    assert trade["sell_quantity"] == trade["buy_quantity"]
    assert not trade["is_partial_exit"]
    assert trade["sell_reason"] == "momentum_warning_sell_1_sell_2_full_exit"


def test_metrics_counts_multiple_exit_events_as_one_closed_position():
    result = BacktestResult(
        final_value=210_000.0,
        nav=pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2025-01-01"]),
            "nav": [200_000.0, 210_000.0],
        }),
        trades=pd.DataFrame({
            "position_id": [0, 0],
            "pnl": [1_000.0, 2_000.0],
            "buy_cost": [5_000.0, 5_000.0],
        }),
        ignored_buy_signals=0,
    )

    metrics = _metrics(result)

    assert metrics["closed_trade_count"] == 1
    assert metrics["win_rate_pct"] == 100.0
