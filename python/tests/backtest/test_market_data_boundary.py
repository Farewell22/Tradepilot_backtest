import pandas as pd

from python.backtest.market_data import normalize_etf_history, normalize_etf_intraday


def test_shared_etf_normalizers_keep_daily_and_intraday_granularity():
    source = pd.DataFrame({
        "时间": ["2024-01-02 09:30:00", "2024-01-02 10:30:00"],
        "开盘价": [10.0, 10.2], "最高价": [10.3, 10.4],
        "最低价": [9.9, 10.0], "收盘价": [10.2, 10.1],
        "成交量": [100, 200],
    })
    daily = normalize_etf_history(source)
    intraday = normalize_etf_intraday(source)
    assert len(daily) == 1
    assert daily.iloc[0][["open", "high", "low", "close", "volume"]].tolist() == [10.0, 10.4, 9.9, 10.1, 300]
    assert len(intraday) == 2
    assert intraday.iloc[0]["date"] == pd.Timestamp("2024-01-02 09:30:00")
