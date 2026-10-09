import pandas as pd
import pytest

from python.research.amv.amv_sell_momentum.study import (
    assign_momentum_quintiles,
    build_sell_candidates,
    summarize_momentum_effect,
)


def test_build_sell_candidates_uses_prior_p85_without_ma3_confirmation() -> None:
    amv = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=40, freq="D"),
            "close": [100.0] * 39 + [120.0],
        }
    )

    candidates = build_sell_candidates(amv, window=3, min_periods=3)

    last = candidates.iloc[-1]
    assert last["gap10_p85"] < last["gap10"]
    assert last["sell_1_candidate"]
    assert last["sell_2_candidate"]


def test_build_sell_candidates_excludes_high_gap_when_ma10_not_above_ma30() -> None:
    closes = [200.0 - 2.0 * index for index in range(39)] + [160.0]
    amv = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=40, freq="D"),
            "close": closes,
        }
    )

    candidates = build_sell_candidates(amv, window=3, min_periods=3)

    last = candidates.iloc[-1]
    assert last["gap10"] > last["gap10_p85"]
    assert last["ma10"] <= last["ma30"]
    assert not last["sell_1_candidate"]
    assert not last["sell_2_candidate"]


def test_assign_momentum_quintiles_orders_low_to_high() -> None:
    frame = pd.DataFrame({"momentum_3": [-0.10, -0.05, 0.00, 0.05, 0.10]})

    result = assign_momentum_quintiles(frame)

    assert result["momentum_quintile"].tolist() == ["Q1", "Q2", "Q3", "Q4", "Q5"]


def test_summarize_momentum_effect_reports_q5_minus_q1_and_order() -> None:
    summary = pd.DataFrame(
        {
            "universe": ["u"] * 5,
            "stage": ["train"] * 5,
            "momentum_quintile": ["Q1", "Q2", "Q3", "Q4", "Q5"],
            "return_10d_mean_pct": [-2.0, -1.0, 0.0, 1.0, 2.0],
        }
    )

    result = summarize_momentum_effect(summary, horizons=(10,))

    assert result.iloc[0]["q5_minus_q1_pct"] == 4.0
    assert result.iloc[0]["group_spearman"] == pytest.approx(1.0)
    assert result.iloc[0]["supports_low_momentum_sell"]
