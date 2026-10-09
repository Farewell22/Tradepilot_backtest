import pandas as pd
import pytest

from python.research.etf.amv_down_momentum_defensive_etfs.study import (
    build_events,
    label_events,
    total_return,
)


def test_build_events_uses_actual_macd_cross_and_three_session_momentum():
    dates = pd.bdate_range("2024-01-01", periods=45)
    amv = pd.DataFrame({"date": dates, "close": [100.0] * 30 + [110.0] * 8 + [100.0] * 7})
    events = build_events(amv)
    assert len(events) == 1
    assert events.iloc[0]["date"] == dates[38]
    assert events.iloc[0]["momentum_3"] == pytest.approx(100 / 110 - 1)
    assert bool(events.iloc[0]["severe_drop"])


def test_total_return_handles_split_and_dividend_entitlement():
    entry = pd.Timestamp("2024-04-11")
    exit_date = pd.Timestamp("2024-04-12")
    assert total_return("515220.SH", entry, exit_date, 2.0, 1.1, dividend_events=()) == pytest.approx(0.10)
    events = (("510880.SH", "2024-01-22", "2024-01-23", "2024-01-26", 0.131),)
    assert total_return("510880.SH", pd.Timestamp("2024-01-22"), pd.Timestamp("2024-01-23"), 2.0, 2.0, dividend_events=events) == pytest.approx(0.131 / 2)
    assert total_return("510880.SH", pd.Timestamp("2024-01-23"), pd.Timestamp("2024-01-24"), 2.0, 2.0, dividend_events=events) == pytest.approx(0)
    old_dividend = (("515220.SH", "2023-12-27", "2023-12-28", "2024-01-03", 0.05),)
    assert total_return("515220.SH", pd.Timestamp("2023-12-26"), pd.Timestamp("2024-04-12"), 2.0, 1.0, dividend_events=old_dividend) == pytest.approx(0.025)


def test_label_events_uses_common_next_open_and_marks_missing_horizon():
    dates = pd.bdate_range("2024-05-01", periods=4)
    daily = pd.DataFrame({"date": dates, "open": [10.0, 11.0, 12.0, 13.0], "close": [10.0, 11.5, 12.5, 13.5]})
    events = pd.DataFrame({"date": [dates[0], dates[2]], "momentum_3": [-0.05, -0.01], "severe_drop": [True, False], "ma10_below_ma30": [True, False]})
    result = label_events(events, {code: daily for code in ("510880.SH", "515220.SH", "512100.SH")}, horizons=(1, 3))
    assert result.loc[0, "entry_date"] == dates[1]
    assert result.loc[0, "510880.SH_return_1d_pct"] == pytest.approx((11.5 / 11 - 1) * 100)
    assert result.loc[0, "510880.SH_return_3d_pct"] == pytest.approx((13.5 / 11 - 1) * 100)
    assert pd.isna(result.loc[1, "510880.SH_return_3d_pct"])
    assert result.loc[0, "510880.SH_excess_1d_pct"] == pytest.approx(0)
