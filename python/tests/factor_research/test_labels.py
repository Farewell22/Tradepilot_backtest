import pandas as pd
import pytest

from python.factor_research.labels import (
    build_breadth_labels,
    build_forward_return_labels,
)


def test_forward_return_uses_hth_subsequent_trading_row():
    prices = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "close": [100.0, 110.0, 121.0],
        }
    )

    labels = build_forward_return_labels(prices, horizons=[2], prefix="sh_index")

    assert labels.iloc[0]["sh_index_forward_return_2"] == pytest.approx(0.21)
    assert pd.isna(labels.iloc[1]["sh_index_forward_return_2"])


def test_breadth_excludes_missing_endpoints_and_counts_each_direction():
    closes = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "AAA": [10.0, 11.0, 12.0],
            "BBB": [20.0, float("nan"), 19.0],
            "CCC": [float("nan"), 10.0, 10.0],
        }
    )

    labels = build_breadth_labels(closes, horizons=[2])

    row = labels.iloc[0]
    assert row["eligible_count_2"] == 2
    assert row["advancers_2"] == 1
    assert row["decliners_2"] == 1
    assert row["unchanged_2"] == 0
    assert row["advance_ratio_2"] == pytest.approx(0.5)
    assert pd.isna(labels.iloc[1]["eligible_count_2"])
