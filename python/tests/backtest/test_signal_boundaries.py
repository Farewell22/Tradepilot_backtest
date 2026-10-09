import pandas as pd

from python.factors.amv_signals import align_amv_sell_signals
from python.factors.amv_gap import generate_buy_signals


def test_amv_sell_labels_can_be_used_without_strategy_module():
    etf = pd.DataFrame({"时间": ["2024-01-02 10:30:00"], "收盘价": [10.0]})
    signals = pd.DataFrame({
        "date": ["2024-01-02"], "sell_types": [["sell_1"]],
        "sell_warning_types": [[]], "signal_type": ["best"],
    })
    annotated = align_amv_sell_signals(etf, signals)
    assert annotated.loc[0, "amv_sell_types"] == "sell_1"
    assert annotated.loc[0, "amv_buy_types"] == "best"


def test_gap_signals_require_history():
    amv = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=15), "close": [10.0] * 15})
    assert generate_buy_signals(amv).empty
