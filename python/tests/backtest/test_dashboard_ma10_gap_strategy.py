import pandas as pd

from python.backtest_dashboard import service


def test_load_ma10_gap_strategy_kline_reads_stage_trades_and_etf_bars(tmp_path, monkeypatch):
    etf_path = tmp_path / "510300.csv"
    pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
        "open": [3.0, 3.1, 3.2], "high": [3.1, 3.2, 3.3],
        "low": [2.9, 3.0, 3.1], "close": [3.05, 3.15, 3.25], "volume": [100, 110, 120],
    }).to_csv(etf_path, index=False)
    run_dir = tmp_path / "strategy"
    run_dir.mkdir()
    pd.DataFrame({"date": ["2024-01-02", "2024-01-04"], "nav": [200000, 210000]}).to_csv(
        run_dir / "nav_oos_class_2_3_combined.csv", index=False
    )
    pd.DataFrame({
        "buy_date": ["20240102"], "sell_date": ["20240104"],
        "buy_exec_price": [3.01], "sell_exec_price": [3.24],
        "buy_signal_type": ["class_2"], "pnl_pct": [7.0], "sell_reason": ["sell_signal_sell_2"],
        "sell_quantity": [500], "is_partial_exit": [True], "position_after_quantity": [500],
    }).to_csv(run_dir / "trades_oos_class_2_3_combined.csv", index=False)
    monkeypatch.setattr(service, "ETF_DATA_PATH", etf_path)
    monkeypatch.setattr(service, "MA10_GAP_STRATEGY_RUN_DIR", run_dir)

    result = service.load_ma10_gap_strategy_kline("oos")

    assert [bar.date for bar in result.bars] == ["20240102", "20240103", "20240104"]
    assert len(result.trades) == 1
    assert result.trades[0].signal_type == "class_2"
    assert result.trades[0].sell_reason == "sell_signal_sell_2"
    assert result.trades[0].is_partial_exit
    assert result.trades[0].sell_quantity == 500


def test_load_dividend_low_vol_strategy_kline_reads_510880_results(tmp_path, monkeypatch):
    etf_path = tmp_path / "510880.csv"
    pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03"],
        "open": [2.0, 2.1], "high": [2.1, 2.2], "low": [1.9, 2.0],
        "close": [2.05, 2.15], "volume": [100, 110],
    }).to_csv(etf_path, index=False)
    run_dir = tmp_path / "strategy"
    run_dir.mkdir()
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "nav": [200000, 201000]}).to_csv(
        run_dir / "nav_oos_class_2_3_combined.csv", index=False
    )
    pd.DataFrame({
        "buy_date": ["20240102"], "sell_date": ["20240103"],
        "buy_exec_price": [2.01], "sell_exec_price": [2.14],
        "buy_signal_type": ["class_2"], "pnl_pct": [6.0], "sell_reason": ["trend_exit_ma10_le_ma30"],
    }).to_csv(run_dir / "trades_oos_class_2_3_combined.csv", index=False)
    monkeypatch.setattr(service, "DIVIDEND_LOW_VOL_ETF_DATA_PATH", etf_path)
    monkeypatch.setattr(service, "DIVIDEND_LOW_VOL_STRATEGY_RUN_DIR", run_dir)

    result = service.load_dividend_low_vol_strategy_kline("oos")

    assert result.symbol == "510880.SH"
    assert len(result.bars) == 2
    assert result.trades[0].sell_reason == "trend_exit_ma10_le_ma30"
