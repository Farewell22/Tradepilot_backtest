import pandas as pd
import pytest

from python.research.etf.industry_etf_relative_strength.study import (
    aggregate_intraday_etf,
    assign_cross_section_deciles,
    attach_forward_returns,
    build_relative_strength_observations,
    classify_industry_behavior,
    filter_buy_event_observations,
    select_non_overlapping_events,
)


def test_aggregate_intraday_etf_builds_daily_ohlcv() -> None:
    raw = pd.DataFrame(
        {
            "时间": ["2024-01-02 10:30", "2024-01-02 15:00"],
            "开盘价": [10.0, 10.5],
            "最高价": [10.8, 11.2],
            "最低价": [9.9, 10.4],
            "收盘价": [10.5, 11.0],
            "成交量": [100, 200],
            "成交额": [1000, 2200],
        }
    )

    daily = aggregate_intraday_etf(raw)

    assert daily.loc[0, ["open", "high", "low", "close", "volume", "amount"]].tolist() == [10.0, 11.2, 9.9, 11.0, 300.0, 3200.0]


def test_build_relative_strength_uses_etf_and_benchmark_returns_at_signal_close() -> None:
    dates = pd.date_range("2024-01-01", periods=21, freq="B")
    etf = pd.DataFrame({"date": dates, "open": [10.0] * 21, "close": [10.0] * 20 + [12.0]})
    benchmark = pd.DataFrame({"date": dates, "open": [10.0] * 21, "close": [10.0] * 20 + [11.0]})

    result = build_relative_strength_observations(etf, benchmark, code="industry", name="行业", industry="行业", lookbacks=(20,))

    assert result.loc[20, "etf_return_20"] == pytest.approx(0.20)
    assert result.loc[20, "reference_return_20"] == pytest.approx(0.10)
    assert result.loc[20, "rs_20"] == pytest.approx(0.10)


def test_attach_forward_returns_enters_next_open_and_computes_benchmark_excess() -> None:
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    observations = pd.DataFrame({"date": [dates[0]]})
    etf = pd.DataFrame({"date": dates, "open": [10.0, 11.0, 12.0, 13.0, 14.0], "close": [10.0, 11.5, 12.5, 13.5, 14.5]})
    benchmark = pd.DataFrame({"date": dates, "open": [20.0, 20.0, 20.0, 20.0, 20.0], "close": [20.0, 21.0, 22.0, 23.0, 24.0]})

    result = attach_forward_returns(observations, etf, benchmark, horizons=(3,))

    assert result.loc[0, "entry_date"] == dates[1]
    assert result.loc[0, "forward_return_3_pct"] == pytest.approx((13.5 / 11.0 - 1.0) * 100.0)
    assert result.loc[0, "excess_return_3_pct"] == pytest.approx((13.5 / 11.0 - 1.0) * 100.0 - (23.0 / 20.0 - 1.0) * 100.0)


def test_assign_cross_section_deciles_excludes_days_with_fewer_than_ten_etfs() -> None:
    date = pd.Timestamp("2024-01-02")
    frame = pd.DataFrame({"date": [date] * 9 + [date + pd.Timedelta(days=1)] * 10, "rs_20": list(range(19))})

    result = assign_cross_section_deciles(frame)

    assert result.loc[result["date"] == date, "cross_section_decile"].isna().all()
    assert result.loc[result["date"] != date, "cross_section_decile"].tolist() == [f"Q{index}" for index in range(1, 11)]


def test_filter_buy_event_observations_keeps_only_requested_class_2_and_class_3_dates() -> None:
    observations = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "code": ["industry"] * 3,
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "signal_type": ["class_1", "class_2", "class_3"],
        }
    )

    result = filter_buy_event_observations(observations, signals, {"class_2", "class_3"})

    assert result[["date", "signal_type"]].to_dict("records") == [
        {"date": pd.Timestamp("2024-01-03"), "signal_type": "class_2"},
        {"date": pd.Timestamp("2024-01-04"), "signal_type": "class_3"},
    ]


def test_select_non_overlapping_events_keeps_first_event_in_a_twenty_session_window() -> None:
    sessions = pd.date_range("2024-01-02", periods=45, freq="B")
    events = pd.DataFrame(
        {
            "date": [sessions[0], sessions[10], sessions[20]],
            "signal_type": ["class_3"] * 3,
        }
    )

    result = select_non_overlapping_events(events, sessions, min_gap_sessions=20)

    assert result["date"].tolist() == [sessions[0], sessions[20]]


def test_classify_industry_behavior_requires_two_consistent_horizons() -> None:
    summary = pd.DataFrame(
        {
            "code": ["continuation"] * 3 + ["mean_reversion"] * 3 + ["mixed"] * 3,
            "horizon": [5, 10, 20] * 3,
            "q10_minus_q1_pct": [1.0, 2.0, -0.1, -1.0, -2.0, 0.1, 1.0, -1.0, 0.0],
        }
    )

    result = classify_industry_behavior(summary)

    assert result.set_index("code")["behavior"].to_dict() == {
        "continuation": "continuation",
        "mean_reversion": "mean_reversion",
        "mixed": "mixed",
    }
