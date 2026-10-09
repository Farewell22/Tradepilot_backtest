from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from python.backtest.broker import FeeConfig
from python.strategies.etf_amv import runner
from python.strategies.etf_amv.strategy import (
    AmvSignalDetector,
    EtfPortfolio,
    align_amv_sell_signals,
    normalize_etf_history,
)


def _amv(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.date_range("2024-01-01", periods=len(closes), freq="D"), "close": closes})


def _etf(days: int = 40, price: float = 10.0) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    return pd.DataFrame({
        "date": dates,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": 1_000_000,
    })


def test_signal_detector_classifies_best_secondary_and_worst_with_priority():
    closes = [25.0] * 60 + [27.0] + [27.0] * 5
    amv = _amv(closes)
    amv.loc[62, "close"] = 28.2

    signals = AmvSignalDetector().detect(amv)

    assert set(signals["signal_type"]) >= {"best", "worst"}
    assert signals.loc[signals["date"] == pd.Timestamp("2024-03-01"), "signal_type"].iloc[0] == "best"


def test_signal_detector_waits_up_to_five_sessions_for_momentum_and_ma60_filter():
    closes = [25.0] * 60 + [25.5, 25.5, 25.5, 25.5, 27.0]
    amv = _amv(closes)

    signals = AmvSignalDetector().detect(amv)

    assert signals.loc[signals["date"] == pd.Timestamp("2024-03-05"), "signal_type"].iloc[0] == "best"


def test_normalize_etf_history_accepts_akshare_columns_and_sorts():
    raw = pd.DataFrame({
        "日期": ["2024-01-02", "2024-01-01"],
        "开盘": [10.2, 10.0],
        "最高": [10.4, 10.3],
        "最低": [10.1, 9.9],
        "收盘": [10.3, 10.2],
        "成交量": [100, 90],
    })

    normalized = normalize_etf_history(raw)

    assert list(normalized.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert normalized.iloc[0]["date"] == pd.Timestamp("2024-01-01")


def test_etf_portfolio_uses_per_run_fees_for_entry():
    no_fees = FeeConfig.stock_legacy().with_overrides(
        commission_rate=0.0, min_commission=0.0,
        stamp_duty_rate=0.0, transfer_fee_rate=0.0, slippage_rate=0.0,
    )
    portfolio = EtfPortfolio(initial_cash=100_000.0, fees=no_fees)
    position = portfolio.apply_signal("20240102", 0, "best", 10.0)
    assert position is not None
    assert position.trade.buy_exec_price == 10.0
    assert position.trade.buy_cost == 100_000.0


def test_normalize_etf_history_aggregates_intraday_rows_to_daily_ohlcv():
    raw = pd.DataFrame({
        "时间": ["2024-01-02 09:30:00", "2024-01-02 10:30:00"],
        "代码": ["510300.SH", "510300.SH"],
        "名称": ["ETF", "ETF"],
        "开盘价": [10.0, 10.2], "收盘价": [10.2, 10.1],
        "最高价": [10.3, 10.4], "最低价": [9.9, 10.0],
        "成交量": [100, 200],
    })

    normalized = normalize_etf_history(raw)

    assert len(normalized) == 1
    assert normalized.iloc[0][["open", "high", "low", "close", "volume"]].tolist() == [10.0, 10.4, 9.9, 10.1, 300]


def test_align_amv_sell_signals_repeats_daily_labels_for_intraday_etf_rows():
    etf = pd.DataFrame({
        "时间": ["2024-01-02 10:30:00", "2024-01-02 14:30:00", "2024-01-03 10:30:00"],
        "代码": ["510300.SH"] * 3,
        "收盘价": [10.0, 10.1, 10.2],
    })
    signals = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02"]),
        "signal_type": ["best"],
        "sell_types": [["sell_1", "sell_2"]],
        "sell_warning_types": [["sell_2"]],
        "sell_momentum_warning_types": [["sell_1"]],
    })

    annotated = align_amv_sell_signals(etf, signals)

    assert annotated["amv_sell_types"].tolist() == ["sell_1|sell_2", "sell_1|sell_2", ""]
    assert annotated["amv_buy_types"].tolist() == ["best", "best", ""]
    assert annotated["amv_sell_warning_types"].tolist() == ["sell_2", "sell_2", ""]
    assert annotated["amv_sell_momentum_warning_types"].tolist() == ["sell_1", "sell_1", ""]


def test_etf_runner_normalizes_numeric_yaml_symbol_to_string(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "symbol: 510300\npaths: {}\nsample: {}\nstrategy: {}\n",
        encoding="utf-8",
    )

    settings = runner.load_settings(config)

    assert settings["symbol"] == "510300"


def test_signal_schedule_does_not_map_old_history_to_stage_first_day():
    signals = pd.DataFrame({
        "date": pd.to_datetime(["1993-04-08", "2023-12-29", "2024-01-10"]),
        "close": [100.0, 100.0, 100.0],
        "momentum_3": [0.05, 0.05, 0.05],
        "signal_type": ["best", "worst", "best"],
    })
    etf_dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-11"])

    scheduled, _ = runner.build_signal_schedule(signals, etf_dates, "20240101", "20240131")

    assert scheduled["signal_date"].tolist() == ["20231229", "20240110"]
    assert scheduled["execution_date"].tolist() == ["20240102", "20240111"]


def test_runner_can_disable_worst_signals():
    signals = pd.DataFrame({"signal_type": ["best", "secondary", "worst"]})

    filtered = runner.filter_signal_types(signals, {"best", "secondary"})

    assert filtered["signal_type"].tolist() == ["best", "secondary"]


def test_runner_ma60_filter_keeps_only_signals_above_ma60():
    amv = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=61, freq="D"),
        "close": [10.0] * 60 + [11.0],
    })
    signals = pd.DataFrame({
        "date": pd.to_datetime(["2024-02-29", "2024-03-01"]),
        "signal_type": ["best", "secondary"],
    })

    filtered = runner.filter_signals_above_ma60(signals, amv)

    assert filtered["date"].tolist() == [pd.Timestamp("2024-03-01")]


def test_runner_ma10_gap_filter_uses_prior_quantiles_and_vetoes_extreme_non_rising():
    amv = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=770, freq="D"),
        "close": [10.0] * 760 + [10.1] * 4 + [12.0] * 3 + [12.0] * 3,
    })
    signals = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-30", "2026-02-06"]),
        "signal_type": ["best", "secondary"],
    })

    filtered = runner.filter_signals_by_ma10_gap(signals, amv, min_quantile=0.5, veto_quantile=0.95)

    assert filtered["date"].tolist() == [pd.Timestamp("2026-01-30")]


def test_portfolio_enters_at_target_weight_and_upgrades_only_to_stronger_signal():
    portfolio = EtfPortfolio(initial_cash=100_000)
    portfolio.apply_signal("20240102", 1, "worst", 10.0)
    assert portfolio.position is not None
    assert portfolio.position.quantity == 2_400
    assert portfolio.position.trade.buy_signal_type == "worst"

    portfolio.apply_signal("20240103", 2, "secondary", 10.0)
    assert portfolio.position.quantity == 4_900
    portfolio.apply_signal("20240104", 3, "worst", 10.0)
    assert portfolio.position.quantity == 4_900

    portfolio.apply_signal("20240105", 4, "best", 10.0)
    assert portfolio.position.quantity == 9_900
    assert portfolio.position.signal_type == "best"


def test_portfolio_can_upgrade_from_half_to_full_with_fees_and_lot_rounding():
    portfolio = EtfPortfolio(initial_cash=200_000)
    portfolio.apply_signal("20240102", 1, "secondary", 3.483)
    portfolio.apply_signal("20240103", 2, "best", 3.478)

    assert portfolio.position is not None
    assert portfolio.position.signal_type == "best"
    assert portfolio.position.quantity > 50_000
    assert portfolio.cash < 1_000


def test_portfolio_uses_signal_specific_stop_and_take_profit():
    portfolio = EtfPortfolio(
        initial_cash=100_000,
        stop_loss={"best": 0.05, "secondary": 0.05, "worst": 0.05},
        profit_trail_threshold=0.08,
    )
    portfolio.apply_signal("20240102", 1, "secondary", 10.0)
    portfolio.process_intraday_bar("20240102 10:30", 1, {
        "open": 10.0, "high": 10.1, "low": 9.6, "close": 9.7,
    }, None)
    assert not portfolio.closed_trades
    portfolio.process_intraday_bar("20240103 10:30", 2, {
        "open": 10.0, "high": 10.1, "low": 9.5, "close": 9.6,
    }, None)
    assert portfolio.closed_trades[-1].sell_reason == "stop_loss_secondary_5pct"

    portfolio = EtfPortfolio(initial_cash=100_000, profit_trail_threshold=0.08)
    portfolio.apply_signal("20240102", 1, "best", 10.0)
    portfolio.process_intraday_bar("20240102 10:30", 1, {
        "open": 10.0, "high": 10.9, "low": 10.3, "close": 10.6,
    }, None)
    assert not portfolio.closed_trades
    portfolio.update_daily_take_profit(10.7, 10.8)
    portfolio.process_intraday_bar("20240103 11:30", 2, {
        "open": 10.8, "high": 10.9, "low": 10.69, "close": 10.7,
    }, None)
    assert portfolio.closed_trades[-1].sell_reason == "profit_trail_body_break_best"


def test_profit_trail_uses_previous_body_low_after_eight_percent_trigger():
    portfolio = EtfPortfolio(initial_cash=100_000, profit_trail_threshold=0.08)
    portfolio.apply_signal("20240102", 1, "best", 10.0)
    portfolio.process_intraday_bar("20240102 10:30", 1, {
        "open": 10.0, "high": 10.9, "low": 10.5, "close": 10.8,
    }, None)

    portfolio.update_daily_take_profit(10.5, 10.8)
    assert portfolio.position is not None
    assert portfolio.position.take_profit_price == 10.5

    portfolio.process_intraday_bar("20240103 10:30", 2, {
        "open": 10.8, "high": 10.9, "low": 10.49, "close": 10.6,
    }, None)
    assert portfolio.closed_trades[-1].sell_reason == "profit_trail_body_break_best"


def test_sell_signal_forces_full_exit_at_next_session_open():
    portfolio = EtfPortfolio(initial_cash=100_000)
    portfolio.apply_signal("20240102", 1, "best", 10.0)

    closed = portfolio.force_sell("20240103", 2, 10.2, "sell_signal_1")

    assert closed is not None
    assert portfolio.position is None
    assert portfolio.closed_trades[-1].sell_reason == "sell_signal_1"
    assert portfolio.closed_trades[-1].sell_time == "open"


def test_portfolio_exits_no_later_than_tenth_trading_day():
    portfolio = EtfPortfolio(initial_cash=100_000)
    portfolio.apply_signal("20240102", 1, "worst", 10.0)
    for day_index in range(2, 12):
        portfolio.process_day_close(
            f"202401{day_index + 1:02d}", day_index, 10.0,
        )

    assert portfolio.closed_trades[-1].sell_reason == "time_exit_t10_worst"


def test_worst_signal_uses_twenty_five_percent_weight_and_three_percent_stop():
    portfolio = EtfPortfolio(
        initial_cash=100_000,
        target_weights={"best": 1.0, "secondary": 0.5, "worst": 0.25},
        stop_loss={"best": 0.05, "secondary": 0.05, "worst": 0.03},
        profit_trail_threshold=0.05,
    )
    portfolio.apply_signal("20240102", 1, "worst", 10.0)

    assert portfolio.position is not None
    assert portfolio.position.quantity == 2_400

    portfolio.process_intraday_bar("20240103 10:30", 2, {
        "open": 10.0, "high": 10.1, "low": 9.69, "close": 9.8,
    }, None)
    assert portfolio.closed_trades[-1].sell_reason == "stop_loss_worst_3pct"


def test_signal_specific_profit_trail_thresholds_are_respected():
    portfolio = EtfPortfolio(
        initial_cash=100_000,
        profit_trail_threshold={"best": 0.08, "secondary": 0.08, "worst": 0.05},
    )
    portfolio.apply_signal("20240102", 1, "worst", 10.0)
    portfolio.process_intraday_bar("20240102 10:30", 1, {
        "open": 10.0, "high": 10.6, "low": 10.1, "close": 10.5,
    }, None)
    portfolio.update_daily_take_profit(10.4, 10.5)

    assert portfolio.position is not None
    assert portfolio.position.take_profit_price == 10.4
