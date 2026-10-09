import pandas as pd
import pytest

import python.research.etf.etf_rs20_rotation.study as rs20_rotation
from python.research.etf.etf_kdj_rotation.study import RotationResult
from python.research.etf.etf_rs20_rotation.study import (
    REFERENCE_ETF,
    build_selection_schedule,
    candidate_rs20,
    choose_rs20_candidate,
)


def test_choose_rs20_candidate_selects_the_highest_available_rs20():
    candidates = pd.DataFrame([
        {"code": "512660.SH", "name": "军工", "rs20": 0.03},
        {"code": "159928.SZ", "name": "消费", "rs20": 0.05},
    ])

    selected = choose_rs20_candidate(candidates)

    assert selected.code == "159928.SZ"
    assert selected.rs20 == pytest.approx(0.05)


def test_choose_rs20_candidate_uses_code_as_a_deterministic_tiebreaker():
    candidates = pd.DataFrame([
        {"code": "512760.SH", "name": "芯片", "rs20": 0.05},
        {"code": "159928.SZ", "name": "消费", "rs20": 0.05},
    ])

    selected = choose_rs20_candidate(candidates)

    assert selected.code == "159928.SZ"


def test_candidate_rs20_requires_twenty_prior_matched_reference_sessions():
    dates = pd.bdate_range("2024-01-01", periods=21)
    reference = pd.DataFrame({"date": dates, "close": range(100, 121)})
    candidate = pd.DataFrame({"date": dates[1:], "close": range(50, 70)})

    result = candidate_rs20(dates[-1], {"159928.SZ": candidate}, reference)

    assert result.empty


def test_candidate_rs20_does_not_use_closes_after_the_signal_date():
    dates = pd.bdate_range("2024-01-01", periods=21)
    reference = pd.DataFrame({"date": dates, "close": range(100, 121)})
    candidate = pd.DataFrame({"date": dates, "close": range(50, 71)})
    as_of = dates[-1]

    before = candidate_rs20(as_of, {"159928.SZ": candidate}, reference)
    future_dates = pd.bdate_range("2024-02-01", periods=2)
    after = candidate_rs20(
        as_of,
        {"159928.SZ": pd.concat([candidate, pd.DataFrame({"date": future_dates, "close": [1_000, 1_200]})])},
        pd.concat([reference, pd.DataFrame({"date": future_dates, "close": [1, 2]})]),
    )

    assert after.iloc[0]["rs20"] == pytest.approx(before.iloc[0]["rs20"])


def test_selection_schedule_skips_signals_before_the_first_reference_session():
    reference_dates = pd.Series(pd.to_datetime(["2024-01-02", "2024-01-03"]))
    buy_signals = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "signal_type": ["class_2"]})
    reference = pd.DataFrame({"date": reference_dates, "close": [10.0, 10.1]})

    schedule, selections = build_selection_schedule(buy_signals, {}, reference, reference_dates)

    assert schedule == {}
    assert selections.empty


def test_selection_schedule_falls_back_to_510300_when_no_candidate_is_available():
    signal_date = pd.Timestamp("2024-01-29")
    reference_dates = pd.bdate_range("2024-01-01", periods=22)
    reference = pd.DataFrame({"date": reference_dates, "close": range(100, 122)})
    candidate_daily = {"159928.SZ": pd.DataFrame({"date": reference_dates[1:], "close": range(50, 71)})}
    buy_signals = pd.DataFrame({"date": [signal_date], "signal_type": ["class_2"]})

    schedule, selections = build_selection_schedule(
        buy_signals, candidate_daily, reference, pd.Series(reference_dates),
    )

    execution_date = pd.Timestamp("2024-01-30")
    assert schedule[execution_date]["code"] == REFERENCE_ETF
    assert schedule[execution_date]["is_fallback"] is True
    assert selections.iloc[0]["candidate_count"] == 0


def test_selection_schedule_retains_the_selected_etf_display_name():
    reference_dates = pd.Series(pd.bdate_range("2024-01-01", periods=22))
    signal_date = reference_dates.iloc[-2]
    reference = pd.DataFrame({"date": reference_dates, "close": range(100, 122)})
    candidate_daily = {
        "159928.SZ": pd.DataFrame({"date": reference_dates, "close": range(50, 72)}),
    }
    buy_signals = pd.DataFrame({"date": [signal_date], "signal_type": ["class_3"]})

    schedule, selections = build_selection_schedule(
        buy_signals, candidate_daily, reference, reference_dates,
    )

    execution_date = reference_dates.iloc[-1]
    assert schedule[execution_date]["name"] == "消费"
    assert selections.iloc[0]["name"] == "消费"


def test_run_research_labels_oos_trade_ledger_rows_unambiguously(tmp_path, monkeypatch):
    reference_path = tmp_path / "510300.SH.csv"
    raw_reference = pd.DataFrame({
        "date": ["2015-01-02 10:30", "2024-01-02 10:30"],
        "open": [10.0, 10.0], "high": [10.1, 10.1], "low": [9.9, 9.9],
        "close": [10.0, 10.0], "volume": [100, 100],
    })
    raw_reference.to_csv(reference_path, index=False)
    empty_signals = pd.DataFrame(columns=["date", "signal_type"])
    empty_trend = pd.DataFrame(columns=["date", "exit_type"])
    empty_sells = pd.DataFrame(columns=["date", "sell_momentum_warning_types"])

    monkeypatch.setattr(rs20_rotation, "load_amv_csv", lambda _: pd.DataFrame())
    monkeypatch.setattr(
        rs20_rotation,
        "_load_candidate_etfs",
        lambda _: (
            {code: pd.DataFrame() for code in rs20_rotation.CONTINUATION_CANDIDATES},
            {code: pd.DataFrame() for code in rs20_rotation.CONTINUATION_CANDIDATES},
        ),
    )
    monkeypatch.setattr(rs20_rotation, "generate_buy_signals", lambda _: empty_signals)
    monkeypatch.setattr(rs20_rotation, "generate_trend_exit_signals", lambda _: empty_trend)
    monkeypatch.setattr(rs20_rotation, "analyze_amv_buy_points", lambda _: (empty_sells, pd.DataFrame()))

    received_exit_thresholds = []

    def fake_backtest(stage_reference, *_, **kwargs):
        received_exit_thresholds.append(kwargs)
        nav = pd.DataFrame({"date": stage_reference["date"], "nav": [200_000.0] * len(stage_reference)})
        return RotationResult(200_000.0, nav, pd.DataFrame(), 0)

    monkeypatch.setattr(rs20_rotation, "run_rotation_backtest", fake_backtest)

    rs20_rotation.run_research(tmp_path / "amv.csv", tmp_path, reference_path, tmp_path / "out")

    summary = pd.read_csv(tmp_path / "out" / "summary.csv")
    assert "oos_exit_row_count" in summary.columns
    assert "oos_trade_count" not in summary.columns
    assert received_exit_thresholds
    assert all(item["stop_loss_pct"] == pytest.approx(0.03) for item in received_exit_thresholds)
    assert all(item["profit_trail_pct"] == pytest.approx(0.05) for item in received_exit_thresholds)
