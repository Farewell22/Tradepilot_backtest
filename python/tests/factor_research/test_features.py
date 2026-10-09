import pandas as pd
import pytest

from python.factor_research.features import build_0amv_features


def test_rolling_features_use_only_current_and_prior_amv_values():
    """A future-shifted MA or return would fail these hand-calculated values."""
    amv = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "close": [10.0, 20.0, 30.0],
        }
    )

    result = build_0amv_features(amv, ma_windows=[2], return_windows=[1])

    row = result.loc[result["date"] == pd.Timestamp("2024-01-03")].iloc[0]
    assert row["amv_ma_gap_2"] == pytest.approx(20.0 / 15.0 - 1.0)
    assert row["amv_return_1"] == pytest.approx(1.0)
    assert pd.isna(result.iloc[0]["amv_ma_gap_2"])
