from __future__ import annotations

import pandas as pd
import pytest

from python.factors import z_indicators


def _compute(daily: pd.DataFrame, **kwargs) -> pd.DataFrame:
    assert hasattr(z_indicators, "compute_dynamic_weekly_kdj"), "缺少当周动态 KDJ 因子"
    return z_indicators.compute_dynamic_weekly_kdj(daily, **kwargs)


def _daily() -> pd.DataFrame:
    dates = list(pd.date_range("2023-11-03", periods=8, freq="W-FRI"))
    dates += list(pd.to_datetime(["2023-12-25", "2023-12-26", "2023-12-27", "2024-01-02"]))
    return pd.DataFrame({"date": dates, "high": 10.0, "low": 0.0,
                         "close": [5.0] * 8 + [0.0, 10.0, 0.0, 0.0]})


def test_dynamic_week_restarts_from_previous_completed_week() -> None:
    result = _compute(_daily()).set_index("date")

    assert result.loc["2023-12-25", "J"] == pytest.approx(100 / 9)
    assert result.loc["2023-12-26", "J"] == pytest.approx(800 / 9)
    assert result.loc["2023-12-27", "J"] == pytest.approx(100 / 9)
    assert result.loc["2024-01-02", "J"] == pytest.approx(-200 / 27)
    assert result.iloc[:8][["K", "D", "J"]].isna().all().all()


def test_future_prices_cannot_change_prior_dynamic_week() -> None:
    daily = _daily()
    before = _compute(daily.iloc[:9])
    daily.loc[9:, ["high", "low", "close"]] = [1000.0, 0.0, 1000.0]
    after = _compute(daily)

    pd.testing.assert_frame_equal(before, after.iloc[:9].reset_index(drop=True))


def test_split_continuity_uses_only_effective_actions() -> None:
    daily = _daily()
    daily.loc[:, "low"] = 2.0
    split_date = pd.Timestamp("2023-12-26")
    split_raw = daily.copy()
    split_raw.loc[split_raw["date"] >= split_date, ["high", "low", "close"]] /= 2

    result = _compute(split_raw, splits={split_date: 2.0})
    expected = _compute(daily)

    pd.testing.assert_frame_equal(result, expected)
    pd.testing.assert_frame_equal(_compute(split_raw.iloc[:9], splits={split_date: 2.0}),
                                  expected.iloc[:9].reset_index(drop=True))


def test_empty_history_has_readable_indicator_columns() -> None:
    result = _compute(_daily().iloc[:0])

    assert result.empty
    assert list(result.columns) == ["date", "K", "D", "J"]


def test_duplicate_daily_date_is_rejected() -> None:
    with pytest.raises(ValueError, match="重复"):
        _compute(pd.concat([_daily(), _daily().iloc[:1]], ignore_index=True))
