import pandas as pd

from python.backtest_dashboard import service


def test_apply_strategy_buy_signals_replaces_legacy_labels_with_class_2_and_class_3():
    points = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "signal_type": ["best", "secondary", None],
        "forward_return_1_pct": [1.0, -1.0, 2.0],
        "forward_return_3_pct": [2.0, -2.0, 3.0],
        "forward_return_5_pct": [3.0, -3.0, 4.0],
        "forward_return_10_pct": [4.0, -4.0, 5.0],
    })
    strategy_signals = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "signal_type": ["class_2", "class_3", "class_1"],
    })

    labeled, summary = service._apply_strategy_buy_signals(points, strategy_signals)

    assert labeled["signal_type"].tolist() == ["class_2", "class_3", None]
    assert summary.set_index("signal_type").loc["class_2", "signal_name"] == "二类买点"
    assert summary.set_index("signal_type").loc["class_3", "count"] == 1
