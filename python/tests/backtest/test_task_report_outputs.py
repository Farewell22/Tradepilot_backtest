from pathlib import Path

import pandas as pd

from python.backtest.metrics import compute_metrics
from python.backtest.report import write_report
from python.research.amv.ma10_gap import study as ma10_gap
from python.research.etf.amv_down_momentum_defensive_etfs import study as defensive_etfs
from python.strategies.green_doji import strategy as green_doji


def test_ma10_gap_run_writes_top_level_summary_report(tmp_path, monkeypatch):
    monkeypatch.setattr(ma10_gap, "load_settings", lambda _path: {"strategy": {}, "paths": {}})

    def fake_stage(stage, settings, fees=None):
        output = Path(settings["paths"]["output_root"]) / stage
        output.mkdir(parents=True)
        (output / "report.txt").write_text("期末净值: 100000\n总收益率: 0.00 %\n", encoding="utf-8")
        pd.DataFrame({"sell_reason": ["stop_loss"]}).to_csv(output / "trades.csv", index=False)
        return output

    monkeypatch.setattr(ma10_gap, "run_stage", fake_stage)
    result = ma10_gap.run_research(tmp_path / "config.yaml", tmp_path / "runs")
    body = (tmp_path / "runs" / "report.md").read_text(encoding="utf-8")
    assert len(result) == 18
    assert "A_baseline" in body
    assert "secondary-best" in body
    assert "止损次数" in body


def test_down_momentum_report_includes_method_and_full_summary():
    summary = pd.DataFrame({
        "stage": ["oos"], "code": ["510880.SH"], "horizon": [5],
        "events": [12], "mean_excess_pct": [1.25],
    })
    report = defensive_etfs.format_report(summary, {"event_count": 12, "entry": "next common ETF session open"})
    assert "0AMV" in report
    assert "510880.SH" in report
    assert "1.25" in report
    assert "12" in report
    assert "next common ETF session open" in report


def test_no_trade_run_writes_csv_with_normal_trade_columns(tmp_path):
    write_report(tmp_path, compute_metrics(100_000, [], []), [], [])
    trades = pd.read_csv(tmp_path / "trades.csv")
    assert trades.empty
    assert "sell_reason" in trades.columns


def test_green_doji_no_trade_run_writes_parseable_trade_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(green_doji, "scan_trading_days", lambda _start, _end: ["20240924"])
    monkeypatch.setattr(green_doji, "load_5min_bars", lambda _code, _date: pd.DataFrame())
    green_doji.run_backtest(start_date="20240924", end_date="20240924", output_dir=str(tmp_path))
    trades = pd.read_csv(tmp_path / "trades.csv")
    assert trades.empty
    assert "sell_reason" in trades.columns
