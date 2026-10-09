from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def factor():
    return importlib.import_module("python.factors.n_pullback")


def pattern(last_low=13.0, middle_high=15.0):
    values = [10.] * 252 + [10.6, 12., 13., 12.2, 11., 11.7, 14., middle_high,
                            14., 12., 12.7, 16., 18., 16.9, last_low, last_low * 1.01]
    return pd.DataFrame({"date": pd.bdate_range("2018-01-01", periods=len(values)),
                         "open": values, "high": values, "low": values, "close": values})


def test_three_cycles_use_the_weakest_low_not_average():
    frame = pattern()
    r = factor().evaluate_structure(frame, len(frame) - 1)
    assert r["status"] == "valid"
    assert r["factor"] == pytest.approx(13 / 12 - 1)
    assert [r[f"L{i}_price"] for i in range(4)] == [10, 11, 12, 13]
    assert [r[f"H{i}_price"] for i in range(1, 4)] == [13, 15, 18]


def test_one_broken_low_makes_factor_negative():
    frame = pattern(last_low=11.5)
    assert factor().evaluate_structure(frame, len(frame) - 1)["factor"] == pytest.approx(11.5 / 12 - 1)


def test_future_prices_do_not_rewrite_historical_factor():
    frame = pattern()
    extension = pattern().iloc[-5:].copy()
    extension["date"] = pd.bdate_range(frame.date.iloc[-1] + pd.Timedelta(days=1), periods=5)
    extension.loc[:, ["open", "high", "low", "close"]] = 1000.
    full = pd.concat([frame, extension], ignore_index=True)
    assert factor().evaluate_structure(full, len(frame) - 1) == factor().evaluate_structure(frame, len(frame) - 1)


def test_pivot_is_not_visible_before_confirmation():
    frame = pattern()
    pivots = factor().detect_pivots(frame)
    high = next(p for p in pivots if p.kind == "high" and p.price == 18)
    assert high.confirm_index > high.index
    r = factor().evaluate_structure(frame, high.index)
    assert r["status"] != "valid"


def test_new_high_is_not_a_pullback_and_short_history_is_missing():
    frame = pattern()
    frame.loc[len(frame) - 1, ["open", "high", "low", "close"]] = 19
    assert factor().evaluate_structure(frame, len(frame) - 1)["status"] == "breakout"
    assert factor().evaluate_structure(frame.iloc[:100], 99)["status"] == "insufficient_history"
    assert np.isnan(factor().evaluate_structure(frame.iloc[:100], 99)["factor"])


def test_non_rising_highs_are_rejected():
    frame = pattern(middle_high=12.8)
    assert factor().evaluate_structure(frame, len(frame) - 1)["status"] != "valid"


def test_invalid_prices_are_not_valid_structures():
    frame = pattern()
    frame.loc[10, "low"] = np.nan
    with pytest.raises(ValueError, match="价格"):
        factor().detect_pivots(frame)


def test_intraday_low_confirmation_then_gap_down_cannot_form_zero_rise_n():
    frame = pd.DataFrame({'date': pd.bdate_range('2018-01-01', periods=261),
                          'open': [20.] * 252 + [11, 9.4, 9.7, 12, 10.5, 11, 14, 12, 11.5],
                          'close': [20.] * 252 + [11, 9.4, 9.7, 12, 10.5, 11, 14, 12, 11.5],
                          'high': [20.] * 252 + [12, 10, 9.9, 12, 11, 11, 14, 13, 12],
                          'low': [20.] * 252 + [10, 9, 9, 10, 10, 10, 11, 11, 11]})
    r = factor().evaluate_structure(frame, len(frame) - 1)
    assert r['status'] == 'non_positive_rise'
    assert np.isnan(r['factor'])
