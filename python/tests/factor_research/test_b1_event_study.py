import pandas as pd
import pytest

from python.factors.z_indicators import compute_all_indicators

from python.factor_research.b1_event_study import (
    aggregate_bars_to_signal_time,
    attach_lagged_amv_features,
    attach_forward_event_returns,
    compute_provisional_indicators,
)


def test_signal_bar_aggregation_excludes_bars_after_1445():
    bars = pd.DataFrame(
        {
            "code": ["000001.SZ"] * 3,
            "date": ["20240102"] * 3,
            "trade_time": ["2024-01-02 14:40:00", "2024-01-02 14:45:00", "2024-01-02 14:50:00"],
            "open": [10.0, 10.2, 99.0],
            "close": [10.2, 10.5, 99.0],
            "high": [10.3, 10.6, 99.0],
            "low": [9.9, 10.1, 99.0],
            "vol": [100, 200, 999],
            "amount": [1000, 2000, 9999],
            "pre_close": [10.0, 10.0, 10.0],
        }
    )

    actual = aggregate_bars_to_signal_time(bars, "14:45:00")

    row = actual.iloc[0]
    assert row["open"] == 10.0
    assert row["close"] == 10.5
    assert row["high"] == 10.6
    assert row["low"] == 9.9
    assert row["vol"] == 300
    assert row["amount"] == 3000


def test_event_returns_start_at_signal_time_entry_and_end_at_future_close():
    events = pd.DataFrame({"signal_date": ["20240102"], "code": ["000001.SZ"], "entry_price": [10.0]})
    closes = pd.DataFrame(
        {"date": ["20240102", "20240103", "20240104", "20240105"], "000001.SZ": [9.0, 11.0, 12.0, 13.0]}
    )

    actual = attach_forward_event_returns(events, closes, horizons=[1, 3])

    assert actual.loc[0, "exit_close_1"] == 11.0
    assert actual.loc[0, "forward_return_1"] == pytest.approx(0.1)
    assert actual.loc[0, "exit_close_3"] == 13.0
    assert actual.loc[0, "forward_return_3"] == pytest.approx(0.3)


def test_amv_features_for_signal_day_are_taken_from_previous_trading_day():
    events = pd.DataFrame({"signal_date": ["20240103"], "code": ["000001.SZ"]})
    amv_features = pd.DataFrame(
        {
            "date": ["20240102", "20240103"],
            "amv_return_5": [0.12, 0.34],
        }
    )

    actual = attach_lagged_amv_features(events, amv_features)

    assert actual.loc[0, "amv_return_5"] == pytest.approx(0.12)


def test_provisional_indicators_match_recalculation_with_1445_bar():
    dates = pd.bdate_range("2023-01-02", periods=141)
    historical = pd.DataFrame(
        {
            "code": "000001.SZ",
            "date": dates.strftime("%Y%m%d"),
            "open": [10.0 + index * 0.02 for index in range(141)],
            "close": [10.1 + index * 0.02 for index in range(141)],
            "high": [10.3 + index * 0.02 for index in range(141)],
            "low": [9.9 + index * 0.02 for index in range(141)],
            "vol": 1000,
            "amount": 10000,
            "pre_close": 10.0,
        }
    )
    provisional = historical.tail(1).copy()
    provisional.loc[:, ["close", "high", "low"]] = [13.4, 13.5, 13.0]
    expected = compute_all_indicators(pd.concat([historical.iloc[:-1], provisional], ignore_index=True)).iloc[-1]

    actual = compute_provisional_indicators(historical, provisional).iloc[0]

    assert actual["J"] == pytest.approx(expected["J"])
    assert actual["zxdq"] == pytest.approx(expected["zxdq"])
    assert actual["zxdkx"] == pytest.approx(expected["zxdkx"])
