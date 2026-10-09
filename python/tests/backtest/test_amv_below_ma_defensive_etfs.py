from pathlib import Path
from dataclasses import replace
import json
import re
from urllib.parse import unquote

import pandas as pd
import pytest

from python.backtest.broker import FeeConfig
from python.backtest.corporate_actions import CorporateAction


ZERO = FeeConfig.etf_legacy().with_overrides(commission_rate=0, min_commission=0, slippage_rate=0)


def daily():
    dates = pd.bdate_range("2024-01-02", periods=5)
    return pd.DataFrame({"date": dates, "open": [10, 10, 5, 5, 5], "high": [10, 10, 5, 5, 5], "low": [10, 10, 5, 5, 5], "close": [10, 10, 5, 5, 5], "volume": 100})


def signals(states):
    dates = pd.bdate_range("2024-01-01", periods=len(states))
    return pd.DataFrame({"date": dates, "below_ma30": states, "below_ma60": states})


def test_amv_sma_is_causal_and_equality_is_outside_regime():
    from python.factors.amv_ma_regime import compute_amv_ma_regimes
    frame = pd.DataFrame({"date": pd.bdate_range("2023-01-02", periods=65), "close": [10.] * 60 + [8., 8., 10., 11., 12.]})
    result = compute_amv_ma_regimes(frame)
    assert pd.isna(result.ma60.iloc[58])
    assert not result.below_ma30.iloc[59]
    assert result.below_ma60.iloc[60]
    frame.loc[64, "close"] = 10000
    pd.testing.assert_frame_equal(result.iloc[:64], compute_amv_ma_regimes(frame).iloc[:64])


def test_regime_change_fills_next_open_and_terminal_signal_is_not_filled():
    from python.strategies.amv_below_ma_defensive_etfs.runner import run_variant, summarize_variant
    result = run_variant(daily(), signals([False, True, True, False, False, True]), "ETF", 30, [], initial_cash=1000, fees=ZERO)
    assert [(x["date"], x["side"]) for x in result.fills] == [("20240103", "buy"), ("20240105", "sell")]
    assert result.positions == []
    summary, episodes = summarize_variant(result, "ETF", 30, 1000)
    assert len(episodes) == 1
    assert summary["total_return_pct"] == -50
    assert summary["closed_episodes"] == 1


def test_prior_signal_seeds_first_open_and_reinvestment_is_one_episode():
    from python.strategies.amv_below_ma_defensive_etfs.runner import run_variant, summarize_variant
    action = CorporateAction("ETF", "dividend", pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04"), pd.Timestamp("2024-01-05"), cash_per_share=5)
    result = run_variant(daily(), signals([True] * 6), "ETF", 60, [action], initial_cash=1000, fees=ZERO)
    assert [x["date"] for x in result.fills] == ["20240102", "20240108"]
    summary, episodes = summarize_variant(result, "ETF", 60, 1000)
    assert summary["total_return_pct"] == 0
    assert summary["dividend_income"] == 500
    assert summary["closed_episodes"] == 0
    assert len(episodes) == 1
    assert episodes[0]["reinvestment_count"] == 1
    assert episodes[0]["status"] == "open"


def test_exit_signal_wins_over_payment_reinvestment():
    from python.strategies.amv_below_ma_defensive_etfs.runner import run_variant
    action = CorporateAction("ETF", "dividend", pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04"), pd.Timestamp("2024-01-05"), cash_per_share=5)
    result = run_variant(daily(), signals([True, True, True, True, False, False]), "ETF", 30, [action], initial_cash=1000, fees=ZERO)
    assert [x["side"] for x in result.fills] == ["buy", "sell"]
    assert result.cash == 1000


def test_no_regime_yields_cash_and_no_episodes():
    from python.strategies.amv_below_ma_defensive_etfs.runner import run_variant, summarize_variant
    result = run_variant(daily(), signals([False] * 6), "ETF", 30, [], initial_cash=1000, fees=ZERO)
    summary, episodes = summarize_variant(result, "ETF", 30, 1000)
    assert summary["total_return_pct"] == 0
    assert summary["max_drawdown_pct"] == 0
    assert episodes == []


def test_csv_action_audit_has_five_funds_and_all_years_covered():
    from python.strategies.amv_below_ma_defensive_etfs.runner import load_action_inputs
    actions, audit = load_action_inputs()
    assert set(audit["funds"]) == {"512800.SH", "561560.SH", "515220.SH", "512890.SH", "510300.SH"}
    assert sum(action.kind == "dividend" and action.code == "515220.SH" for action in actions) == 4
    assert sum(action.kind == "dividend" and action.code == "510300.SH" for action in actions) == 3
    assert all(item["sources"] for item in audit["funds"].values())


def test_registry_exposes_new_strategy_and_etf_fees():
    from python.task_registry import TASKS
    spec = TASKS[("strategy", "amv_below_ma_defensive_etfs")]
    assert spec.default_fees == FeeConfig.etf_legacy()
    assert spec.execution_mode == "next_open_dividend_reinvestment"
    assert len(spec.data_sources) == 8


@pytest.mark.parametrize(("arguments", "start", "end"), [
    ([], "20220516", "20251231"),
    (["--start", "20240102"], "20240102", "20251231"),
    (["--end", "20240209"], "20220516", "20240209"),
])
def test_builtin_strategy_cli_uses_verified_defaults_and_explicit_overrides(tmp_path, arguments, start, end):
    from python.run_backtest import main
    from python.task_registry import TASKS
    received = []
    def handler(request):
        received.append((request.start_date, request.end_date))
        (request.output_dir / "report.md").write_text("verified run\n")
        return request.output_dir
    key = ("strategy", "amv_below_ma_defensive_etfs")
    spec = replace(TASKS[key], handler=handler, data_sources=(), report_dir=tmp_path / "published")
    assert main(["run", *key, *arguments, "--output-root", str(tmp_path / "runs")], tasks={key: spec}) == 0
    assert received == [(start, end)]
    manifest = json.loads((next((tmp_path / "runs").iterdir()) / "run_manifest.json").read_text())
    assert (manifest["start_date"], manifest["end_date"]) == (start, end)


def sample_sources(tmp_path):
    from python.strategies.amv_below_ma_defensive_etfs.runner import NAMES
    prices = tmp_path / "prices"
    prices.mkdir()
    dates = pd.bdate_range("2023-10-02", "2024-02-09")
    source = pd.DataFrame({"date": dates, "close": 100.})
    source.loc[source.date >= "2024-01-01", "close"] = 80.
    amv_path = tmp_path / "amv.csv"
    source.to_csv(amv_path, index=False)
    for code in NAMES:
        rows = []
        for date in dates:
            for hour in (10.5, 11.5, 14., 15.):
                rows.append({"date": date + pd.Timedelta(hours=hour), "open": 10., "high": 10., "low": 10., "close": 10., "volume": 100})
        pd.DataFrame(rows).to_csv(prices / f"{code}.csv", index=False)
    return amv_path, prices


def test_cli_writes_all_sixteen_comparisons_and_reproducible_artifacts(tmp_path):
    from python.run_backtest import main, TaskSpec
    from python.strategies.amv_below_ma_defensive_etfs.runner import run_backtest
    amv_path, prices = sample_sources(tmp_path)
    def handler(request):
        run_backtest(amv_path, prices, request.output_dir, start_date=request.start_date, end_date=request.end_date, fees=request.fees)
        return request.output_dir
    spec = TaskSpec("sample", "strategy", handler, ZERO, "next_open_dividend_reinvestment", report_dir=tmp_path / "published")
    status = main(["run", "strategy", "sample", "--start", "20240102", "--end", "20240209", "--output-root", str(tmp_path / "runs")], tasks={("strategy", "sample"): spec})
    assert status == 0
    output = next((tmp_path / "runs").iterdir())
    summary = pd.read_csv(output / "summary.csv")
    assert len(summary) == 16
    assert summary.loc[(summary.period > 0) & summary.code.ne("510300.SH")].shape[0] == 8
    assert json.loads((output / "run_manifest.json").read_text())["status"] == "complete"
    metadata = json.loads((output / "execution_metadata.json").read_text())
    assert metadata["trading_days"] == len(pd.bdate_range("2024-01-02", "2024-02-09"))
    assert metadata["source_sha256"]
    assert (output / "ma30_nav_drawdown.png").stat().st_size > 1000
    assert (tmp_path / "published/latest-report.md").exists()


def test_published_report_retains_accessible_chart_links(tmp_path):
    from python.backtest.report_publication import render_latest_report
    from python.strategies.amv_below_ma_defensive_etfs.runner import run_backtest
    amv_path, prices = sample_sources(tmp_path)
    output = tmp_path / "runs"
    run_backtest(amv_path, prices, output, start_date="20240102", end_date="20240209", fees=ZERO)
    publication = tmp_path / "published"
    report = render_latest_report(publication, output, {"task_id": "sample", "kind": "strategy", "generated_at": "now", "start_date": "20240102", "end_date": "20240209"})
    links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", report)
    assert len(links) == 2
    assert all((publication / unquote(link)).is_file() for link in links)


def test_missing_amv_session_is_rejected_instead_of_dropping_etf_day(tmp_path):
    from python.strategies.amv_below_ma_defensive_etfs.runner import run_backtest
    amv_path, prices = sample_sources(tmp_path)
    frame = pd.read_csv(amv_path)
    frame.loc[frame.date.ne("2024-01-10")].to_csv(amv_path, index=False)
    with pytest.raises(ValueError, match="calendar"):
        run_backtest(amv_path, prices, tmp_path / "out", start_date="20240102", end_date="20240209", fees=ZERO)


@pytest.mark.parametrize(("clock", "column"), [("10:30:00", "open"), ("15:00:00", "close"), ("14:00:00", "volume")])
def test_missing_intraday_values_cannot_be_replaced_during_daily_aggregation(tmp_path, clock, column):
    from python.strategies.amv_below_ma_defensive_etfs.runner import run_backtest
    amv_path, prices = sample_sources(tmp_path)
    path = prices / "512800.SH.csv"
    frame = pd.read_csv(path)
    frame.loc[frame.date.eq(f"2024-01-02 {clock}"), column] = float("nan")
    frame.loc[frame.date.eq("2024-01-02 11:30:00"), "open"] = 20.
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="finite intraday"):
        run_backtest(amv_path, prices, tmp_path / "out", start_date="20240102", end_date="20240209", fees=ZERO)


def test_four_bars_with_wrong_first_timestamp_are_rejected(tmp_path):
    from python.strategies.amv_below_ma_defensive_etfs.runner import run_backtest
    amv_path, prices = sample_sources(tmp_path)
    path = prices / "512800.SH.csv"
    frame = pd.read_csv(path)
    frame.loc[frame.date.eq("2024-01-02 10:30:00"), "date"] = "2024-01-02 11:00:00"
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="intraday slots"):
        run_backtest(amv_path, prices, tmp_path / "out", start_date="20240102", end_date="20240209", fees=ZERO)


def test_missing_daily_bar_is_rejected_without_silent_date_intersection(tmp_path):
    from python.strategies.amv_below_ma_defensive_etfs.runner import NAMES, run_backtest
    source = pd.DataFrame({"date": pd.bdate_range("2023-09-01", "2024-01-05"), "close": 100})
    source.to_csv(tmp_path / "amv.csv", index=False)
    # Incomplete first fund: skipping it must not silently shorten the calendar.
    pd.DataFrame({"date": ["2024-01-02 10:30"], "open": [10], "high": [10], "low": [10], "close": [10], "volume": [100]}).to_csv(tmp_path / "512800.SH.csv", index=False)
    with pytest.raises(ValueError, match="incomplete daily"):
        run_backtest(tmp_path / "amv.csv", tmp_path, tmp_path / "out", start_date="20240102", end_date="20240105", fees=ZERO)
