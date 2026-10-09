from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
import yaml

from python.backtest.broker import FeeConfig
from python.run_backtest import RunRequest
from python.strategies.amv_winning_defensive_csi2000.runner import run_primary_variant


def make_case(tmp_path, *, consolidation=False, traded_on_suspension=False, unknown_gap=False):
    dates = pd.to_datetime(["2022-09-01", "2022-09-02", "2022-09-05"]) if consolidation else pd.bdate_range("2021-02-05", "2021-02-10")
    prehistory = pd.bdate_range(end=dates[0] - pd.Timedelta(days=1), periods=12)
    amv = pd.DataFrame({"date": prehistory.append(pd.DatetimeIndex(dates)),
                        "close": [100.] * 12 + [105.] * len(dates)})
    primary = pd.DataFrame({"date": dates + pd.Timedelta(hours=15), "open": 10.,
                            "close": 10., "high": 10., "low": 10., "volume": 100000})
    baseline = primary.copy()
    event = {"date": "2022-09-02" if consolidation else "2021-02-08",
             "code": "512100.SH" if consolidation else "159915.SZ",
             "reason": "fixture verified suspension", "source": "https://example.com/issuer-notice"}
    if consolidation:
        baseline.loc[0, ["open", "high", "low", "close"]] = .982
        baseline.loc[1, ["open", "high", "low", "close", "volume"]] = [.982, .982, .982, .982, 0]
        baseline.loc[2, ["open", "high", "low", "close"]] = 2.713
    elif not traded_on_suspension:
        primary = primary.loc[primary.date.dt.normalize().ne(pd.Timestamp("2021-02-08"))].copy()
        # A zero-volume placeholder must not become a tradable stop bar on resumption day.
        zero_bar = primary.iloc[[1]].copy()
        zero_bar["date"] = pd.Timestamp("2021-02-09 10:30")
        zero_bar["volume"] = 0
        primary = pd.concat([primary, zero_bar], ignore_index=True)
    if unknown_gap:
        baseline = baseline.loc[baseline.date.dt.normalize().ne(dates[-1])].copy()
    paths = {}
    for name, frame in {"amv_csv": amv, "primary_csv": primary, "baseline_primary_csv": baseline,
                        "stock_dividends_csv": pd.DataFrame({"ex_date": ["2020-01-01"], "cash_per_share": [.1], "source": ["fixture"]})}.items():
        path = tmp_path / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = str(path)
    stock_dir = tmp_path / "stock"
    for date in dates:
        target = stock_dir / str(date.year) / f"{date:%Y%m%d}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"trade_time": [date + pd.Timedelta(hours=15)], "code": ["601288.SH"],
                      "open": [5.], "close": [5.], "high": [5.], "low": [5.], "vol": [100000]}).to_parquet(target, index=False)
    paths["stock_5m_dir"] = str(stock_dir)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"paths": paths, "initial_cash": 100000}))
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"suspensions": [event], "drop_zero_volume_intraday_bars": True}))
    request = RunRequest("amv_winning_defensive_chinext", "strategy", dates[0].strftime("%Y%m%d"), dates[-1].strftime("%Y%m%d"),
                         tmp_path / "output", FeeConfig(0, 0, 0, 0, 0), "legacy_same_close_idealized", config)
    return request, policy


def run_case(request, policy):
    return run_primary_variant(request, primary_code="159915.SZ", primary_label="创业板指", variant="chinext",
                               calendar_policy_path=policy)


def test_verified_suspension_is_removed_from_both_clocks_and_audited(tmp_path):
    request, policy = make_case(tmp_path)
    run_case(request, policy)
    nav = pd.read_csv(request.output_dir / "nav.csv")
    assert nav.date.tolist() == ["2021-02-05", "2021-02-09", "2021-02-10"]
    assert pd.read_csv(request.output_dir / "baseline/nav.csv").date.tolist() == nav.date.tolist()
    audit = json.loads((request.output_dir / "calendar_audit.json").read_text())
    assert audit["excluded_sessions"][0]["date"] == "2021-02-08"
    assert audit["excluded_zero_volume_bars"] == [{"code": "159915.SZ", "timestamp": "2021-02-09T10:30:00"}]
    assert (request.output_dir / "inputs/calendar_policy.json").read_bytes() == policy.read_bytes()
    assert "2021-02-08" in (request.output_dir / "report.md").read_text()
    # The AMV indicator still uses the excluded day's 105 close, with its past history.
    signal = pd.read_csv(request.output_dir / "amv_signals.csv").iloc[1]
    assert signal.ma5 == pytest.approx(103.)


def test_suspension_calendar_keeps_consolidation_at_new_quote_boundary(tmp_path):
    request, policy = make_case(tmp_path, consolidation=True)
    run_case(request, policy)
    nav = pd.read_csv(request.output_dir / "baseline/nav.csv")
    assert nav.date.tolist() == ["2022-09-01", "2022-09-05"]
    assert nav.iloc[-1].primary_quantity == 37213
    assert nav.iloc[-1]["nav"] == pytest.approx(100991.269)
    assert pd.read_csv(request.output_dir / "nav.csv").iloc[-1].primary_quantity == 10000


def test_verified_suspension_conflicting_with_traded_bars_fails(tmp_path):
    request, policy = make_case(tmp_path, traded_on_suspension=True)
    with pytest.raises(ValueError, match="停牌.*成交|成交.*停牌"):
        run_case(request, policy)


def test_calendar_policy_does_not_hide_unknown_missing_day(tmp_path):
    request, policy = make_case(tmp_path, unknown_gap=True)
    with pytest.raises(ValueError, match="缺少"):
        run_case(request, policy)


def test_report_actual_start_moves_past_leading_suspension(tmp_path):
    request, policy = make_case(tmp_path, consolidation=True)
    request = replace(request, start_date="20220902")
    run_case(request, policy)
    metrics = json.loads((request.output_dir / "metrics.json").read_text())
    assert metrics["actual_start"] == "20220905"
    assert "实际区间 20220905—20220905" in (request.output_dir / "report.md").read_text()
