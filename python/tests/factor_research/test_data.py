from unittest.mock import Mock

import pandas as pd
import pytest

from python.factor_research.data import IndexCache, load_market_close_panel


def test_existing_index_cache_is_used_without_creating_a_network_source(tmp_path):
    pd.DataFrame(
        {"date": ["2024-01-02"], "open": [3000], "high": [3010], "low": [2990], "close": [3005], "volume": [1]}
    ).to_csv(tmp_path / "sh000001.csv", index=False)
    source_factory = Mock(side_effect=AssertionError("network should not run"))

    actual = IndexCache(tmp_path, source_factory).load("sh000001", "20240102", "20240102")

    assert actual["close"].tolist() == [3005.0]
    source_factory.assert_not_called()


def test_incomplete_index_cache_is_replaced_with_full_history_for_requested_period(tmp_path):
    pd.DataFrame(
        {"date": ["2025-03-19"], "open": [3000], "high": [3010], "low": [2990], "close": [3005], "volume": [1]}
    ).to_csv(tmp_path / "sh000001.csv", index=False)
    full_history = pd.DataFrame(
        {"date": ["2015-01-05", "2026-06-12"], "open": [3000, 4000], "high": [3010, 4010],
         "low": [2990, 3990], "close": [3005, 4005], "volume": [1, 2]}
    )
    loader = Mock(return_value=full_history)

    actual = IndexCache(tmp_path, history_loader=loader).load("sh000001", "20150101", "20260612")

    assert actual["date"].tolist() == [pd.Timestamp("2015-01-05"), pd.Timestamp("2026-06-12")]
    loader.assert_called_once_with("sh000001")


def test_market_close_panel_uses_last_intraday_close_for_each_code(tmp_path):
    path = tmp_path / "2024"
    path.mkdir()
    pd.DataFrame(
        {"code": ["AAA", "AAA", "BBB", "BBB"], "date": ["20240102"] * 4,
         "trade_time": ["09:35", "15:00", "09:35", "15:00"], "close": [10, 11, 20, 19]}
    ).to_parquet(path / "20240102.parquet", index=False)

    panel = load_market_close_panel(tmp_path, "20240102", "20240102")

    assert panel.loc[pd.Timestamp("2024-01-02"), "AAA"] == 11
    assert panel.loc[pd.Timestamp("2024-01-02"), "BBB"] == 19


def test_market_close_panel_uses_available_files_not_weekday_calendar(tmp_path):
    """A weekday holiday must not be mistaken for a missing trading-data file."""
    path = tmp_path / "2024"
    path.mkdir()
    pd.DataFrame(
        {"code": ["AAA"], "date": ["20240102"], "trade_time": ["15:00"], "close": [11]}
    ).to_parquet(path / "20240102.parquet", index=False)

    panel = load_market_close_panel(tmp_path, "20240101", "20240102")

    assert panel.index.tolist() == [pd.Timestamp("2024-01-02")]
