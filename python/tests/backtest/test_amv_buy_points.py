import pandas as pd
import pytest

from python.factors.amv_buy_points import analyze_amv_buy_points, low_momentum_warning


def _amv_frame() -> pd.DataFrame:
    closes = [100.0] * 20 + [110.0, 100.6, 105.0, 116.0, 117.0, 118.0, 119.0]
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
        }
    )


def test_buy_points_calculate_crosses_and_mutually_exclusive_priority():
    points, summary = analyze_amv_buy_points(_amv_frame())

    assert points.loc[points["date"] == pd.Timestamp("2024-01-21"), "signal_type"].iloc[0] == "best"
    assert points.loc[points["date"] == pd.Timestamp("2024-01-23"), "signal_type"].iloc[0] == "secondary"
    assert points.loc[points["date"] == pd.Timestamp("2024-01-24"), "signal_type"].iloc[0] == "worst"
    assert summary.set_index("signal_type").loc["best", "count"] == 1


def test_buy_points_future_returns_use_following_trading_rows_and_ignore_incomplete_tail():
    frame = _amv_frame()
    points, summary = analyze_amv_buy_points(frame, horizons=(1, 3, 10))
    best = points.loc[points["signal_type"] == "best"].iloc[0]

    assert best["forward_return_1_pct"] == pytest.approx((100.6 / 110.0 - 1) * 100)
    assert pd.isna(best["forward_return_10_pct"])
    assert summary.set_index("signal_type").loc["best", "avg_forward_return_1_pct"] == pytest.approx(
        (100.6 / 110.0 - 1) * 100
    )


def test_buy_points_filter_after_features_preserves_indicator_values():
    points, _ = analyze_amv_buy_points(_amv_frame(), start_date="20240122", end_date="20240122")

    assert len(points) == 1
    assert points.iloc[0]["ma20"] == pytest.approx(100.53)


def test_buy_points_reject_missing_ohlcv_columns():
    with pytest.raises(ValueError, match="open"):
        analyze_amv_buy_points(pd.DataFrame({"date": ["2024-01-01"], "close": [1.0]}))


def test_sell_points_mark_ma10_extreme_gap_when_ma3_turns_flat():
    closes = [100.0] * 800 + [129.0, 159.0, 159.0, 129.0]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
        }
    )

    points, _ = analyze_amv_buy_points(frame)

    assert points.iloc[-1]["sell_types"] == ["sell_1", "sell_2"]


def test_sell_points_mark_ma20_extreme_gap_and_can_mark_both_types():
    closes = [100.0] * 800 + [150.0, 220.0, 220.0, 150.0]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
        }
    )

    points, _ = analyze_amv_buy_points(frame)

    assert points.iloc[-1]["sell_types"] == ["sell_1", "sell_2"]


def test_sell_points_do_not_mark_when_ma3_is_rising():
    closes = [100.0] * 800 + [129.0, 159.0, 159.0, 170.0]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
        }
    )

    points, _ = analyze_amv_buy_points(frame)

    assert points.iloc[-1]["sell_types"] == []


def test_sell_points_mark_when_ma3_is_not_rising_even_if_it_was_already_falling():
    closes = [100.0] * 800 + [200.0, 170.0, 170.0, 160.0, 150.0]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
        }
    )

    points, _ = analyze_amv_buy_points(frame)

    assert points.iloc[-1]["sell_types"] == ["sell_1", "sell_2"]


def test_sell_points_use_prior_750_day_rolling_p85_and_p90_warning():
    closes = [100.0] * 800 + [200.0, 170.0, 170.0, 160.0, 150.0]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
        }
    )

    points, _ = analyze_amv_buy_points(frame)

    assert points.iloc[-1]["sell_types"] == ["sell_1", "sell_2"]
    assert points.iloc[-1]["sell_warning_types"] == ["sell_1", "sell_2"]


def test_low_momentum_warning_uses_only_prior_high_gap_candidates():
    momentum = pd.Series([0.05, 0.03, 0.06, 0.04, 0.01])
    high_gap_candidate = pd.Series([True, True, True, True, True])

    warnings = low_momentum_warning(
        momentum,
        high_gap_candidate,
        window=4,
        min_periods=4,
    )

    assert warnings.tolist() == [False, False, False, False, True]
