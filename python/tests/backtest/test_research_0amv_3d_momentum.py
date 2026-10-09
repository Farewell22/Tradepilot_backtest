import pandas as pd
import pytest

from python.research.amv.amv_3d_momentum.study import (
    assign_momentum_deciles,
    attach_etf_forward_returns,
    build_momentum_factor,
)


def test_build_momentum_factor_calculates_three_day_cumulative_return() -> None:
    amv = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="D"),
            "close": [100.0, 105.0, 95.0, 80.0],
        }
    )

    result = build_momentum_factor(amv)

    assert result.loc[3, "momentum_3"] == pytest.approx(-0.20)


def test_attach_returns_keeps_only_amv_and_etf_intersection_dates() -> None:
    factors = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-04"]),
            "momentum_3": [-0.1, 0.0, 0.1],
        }
    )
    etf = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"]),
            "open": [10.0, 11.0, 12.0, 13.0, 14.0],
            "close": [10.5, 11.5, 12.5, 13.0, 14.5],
        }
    )

    result = attach_etf_forward_returns(factors, etf, horizons=(3,))

    assert result["date"].tolist() == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-04")]
    assert result.loc[0, "entry_date"] == pd.Timestamp("2024-01-03")
    assert result.loc[0, "forward_return_3_pct"] == pytest.approx((13.0 / 11.0 - 1.0) * 100.0)


def test_assign_momentum_deciles_orders_lowest_to_highest() -> None:
    frame = pd.DataFrame({"momentum_3": [-0.09, -0.07, -0.05, -0.03, -0.01, 0.01, 0.03, 0.05, 0.07, 0.09]})

    result = assign_momentum_deciles(frame)

    assert result["momentum_decile"].tolist() == [f"Q{index}" for index in range(1, 11)]
