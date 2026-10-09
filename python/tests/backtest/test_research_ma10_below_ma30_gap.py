import pandas as pd
import pytest

from python.research.amv.ma10_below_ma30_gap.study import (
    assign_gap_quintiles,
    attach_etf_forward_returns,
    compute_amv_gap_factor,
    summarize_spreads,
)


def test_compute_amv_gap_factor_keeps_only_ma10_below_ma30_dates():
    dates = pd.date_range("2024-01-01", periods=35, freq="D")
    closes = list(range(100, 65, -1))
    amv = pd.DataFrame({"date": dates, "close": closes})

    result = compute_amv_gap_factor(amv)

    assert not result.empty
    assert (result["ma10"] < result["ma30"]).all()
    last = result.iloc[-1]
    assert last["gap10"] == pytest.approx(last["close"] / last["ma10"] - 1.0)


def test_assign_gap_quintiles_orders_q1_negative_extreme_to_q5_positive_extreme():
    frame = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=10, freq="D"),
        "gap10": [-0.10, -0.08, -0.06, -0.04, -0.02, 0.01, 0.03, 0.05, 0.07, 0.09],
    })

    result = assign_gap_quintiles(frame)

    assert result.loc[result["quintile"] == "Q1", "gap10"].tolist() == [-0.10, -0.08]
    assert result.loc[result["quintile"] == "Q5", "gap10"].tolist() == [0.07, 0.09]
    assert result.groupby("quintile", observed=True)["gap10"].mean().is_monotonic_increasing


def test_attach_etf_forward_returns_enters_at_next_open_and_exits_at_horizon_close():
    factors = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "gap10": [-0.05]})
    etf = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
        "open": [95.0, 100.0, 106.0, 111.0],
        "close": [96.0, 105.0, 110.0, 120.0],
    })

    result = attach_etf_forward_returns(factors, etf, horizons=(1, 3))

    row = result.iloc[0]
    assert row["entry_date"] == pd.Timestamp("2024-01-02")
    assert row["entry_open"] == 100.0
    assert row["forward_return_1_pct"] == pytest.approx(5.0)
    assert row["forward_return_3_pct"] == pytest.approx(20.0)


def test_attach_etf_forward_returns_drops_signals_before_etf_history_begins():
    factors = pd.DataFrame({
        "date": pd.to_datetime(["2023-12-01", "2024-01-01"]),
        "gap10": [-0.10, 0.02],
    })
    etf = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
        "open": [100.0, 101.0],
        "close": [100.5, 102.0],
    })

    result = attach_etf_forward_returns(factors, etf, horizons=(1,))

    assert result["date"].tolist() == [pd.Timestamp("2024-01-01")]
    assert result["entry_date"].tolist() == [pd.Timestamp("2024-01-02")]


def test_summarize_spreads_computes_spearman_without_optional_scipy():
    summary = pd.DataFrame({
        "stage": ["train"] * 5,
        "quintile": ["Q1", "Q2", "Q3", "Q4", "Q5"],
        "return_3d_mean_pct": [-2.0, -1.0, 0.0, 1.0, 2.0],
    })

    result = summarize_spreads(summary, horizons=(3,))

    assert result.loc[0, "q5_minus_q1_pct"] == pytest.approx(4.0)
    assert result.loc[0, "group_spearman"] == pytest.approx(1.0)
    assert result.loc[0, "strictly_increasing"]
