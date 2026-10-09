from __future__ import annotations

import importlib
import json

import numpy as np
import pandas as pd
import pytest


def data():
    return importlib.import_module("python.research.stock.n_pullback_amv_entry.data")


def intraday(date="2024-01-02"):
    times = list(pd.date_range(f"{date} 09:35", f"{date} 11:30", freq="5min"))
    times += list(pd.date_range(f"{date} 13:05", f"{date} 15:00", freq="5min"))
    return pd.DataFrame(dict(code="000001.SZ", trade_time=times, open=10.,
                             high=11., low=9., close=10., vol=100.))


def test_daily_aggregation_sorts_and_flags_missing_close():
    raw = intraday()
    raw.loc[47, "close"] = 10.5
    day = data().aggregate_day(raw.iloc[::-1], pd.Timestamp("2024-01-02"))
    assert day.iloc[0].close == 10.5
    assert day.iloc[0].volume == 4800
    assert bool(day.iloc[0].valid)
    bad = data().aggregate_day(raw.iloc[:-1], pd.Timestamp("2024-01-02"))
    assert not bool(bad.iloc[0].valid)


def test_adjustment_removes_ex_dividend_fake_break():
    dates = pd.bdate_range("2024-01-02", periods=2)
    daily = pd.DataFrame(dict(date=dates, code="601288.SH", open=[10., 9.],
                              high=[10., 9.], low=[10., 9.], close=[10., 9.], valid=True))
    adj = pd.DataFrame(dict(date=dates, code="601288.SH", adj_factor=[1., 10/9]))
    adjusted = data().adjust_prices(daily, adj)
    assert adjusted.close.tolist() == pytest.approx([10, 10])
    assert adjusted.open.tolist() == pytest.approx([10, 10])
    with pytest.raises(ValueError, match="复权"):
        data().adjust_prices(daily, adj.iloc[:1])


def test_forward_labels_use_market_calendar_and_independent_missing_endpoints():
    dates = pd.bdate_range("2024-01-02", periods=22)
    frame = pd.DataFrame(dict(date=dates, code="000001.SZ", open=10.,
                              close=np.arange(10., 32.), low=9., valid=True))
    complete = data().forward_labels(frame, [dates[0]], pd.DatetimeIndex(dates))
    assert complete.iloc[0].mae_5 == pytest.approx(-.1)
    # H=5 targets date[5], even when the stock has a missing date[3].
    frame = frame.drop(index=3)
    labels = data().forward_labels(frame, [dates[0]], pd.DatetimeIndex(dates))
    assert labels.iloc[0].return_5 == pytest.approx(.5)
    assert np.isnan(labels.iloc[0].mae_5)
    assert labels.iloc[0].return_10 == pytest.approx(1.)
    assert labels.iloc[0].return_20 == pytest.approx(2.)
    missing = data().forward_labels(frame[frame.date != dates[1]], [dates[0]], pd.DatetimeIndex(dates))
    assert np.isnan(missing.iloc[0].return_5)
    missing = data().forward_labels(frame[frame.date != dates[10]], [dates[0]], pd.DatetimeIndex(dates))
    assert missing.iloc[0].return_5 == pytest.approx(.5)
    assert np.isnan(missing.iloc[0].return_10)
    assert missing.iloc[0].return_20 == pytest.approx(2.)


def test_event_loader_only_reads_primary_actual_buys_and_respects_scope(tmp_path):
    (tmp_path / "run_manifest.json").write_text(json.dumps(dict(
        task_id="amv_winning_defensive", status="complete", execution_mode="legacy_same_close_idealized")))
    pd.DataFrame(dict(date=[20200102, 20200103, 20200106], code=["512100.SH", "601288.SH", "512100.SH"],
                      side=["buy", "buy", "sell"])).to_csv(tmp_path / "trades_601288.SH.csv", index=False)
    events = data().load_events(tmp_path, "20200101", "20251231")
    assert events.tolist() == [pd.Timestamp("2020-01-02")]


def test_missing_adjustment_cannot_be_forward_filled():
    daily = pd.DataFrame(dict(date=pd.bdate_range("2024-01-01", periods=2), code="000001.SZ",
                              open=10., high=10., low=10., close=10., valid=True))
    adj = pd.DataFrame(dict(date=daily.date[:1], code="000001.SZ", adj_factor=1.))
    with pytest.raises(ValueError, match="复权"):
        data().adjust_prices(daily, adj)


def stats():
    return importlib.import_module("python.research.stock.n_pullback_amv_entry.statistics")


def test_overlapping_market_windows_share_a_cluster():
    calendar = pd.bdate_range("2024-01-01", periods=30)
    assert stats().overlap_clusters(calendar[[0, 4, 10]], calendar, 5).tolist() == [0, 0, 1]


def test_equal_date_weight_does_not_weight_larger_stock_universes():
    dates = pd.bdate_range("2024-01-01", periods=30)
    event_rows = pd.DataFrame(dict(date=dates[[0, 10]], threshold=.05, horizon=5,
                                   group="all_n", mean_return=[0., 1.], mean_excess=[0., 1.],
                                   win_rate=[0., 1.], median_return=[0., 1.], p10=[0., 1.],
                                   mean_mae=[0., 0.], n_labeled=[2, 100], n_input=[2, 100]))
    out = stats().summarize(event_rows, dates, repeats=20)
    full = out[(out.stage == "all") & (out.group == "all_n")].iloc[0]
    assert full.mean_return == .5
    assert full.stock_observations == 102
    assert np.isnan(full.ci_low)


def test_equal_factor_values_are_not_split_into_different_bins():
    frame = pd.DataFrame(dict(factor=[0.] * 60 + [1.] * 10 + [2.] * 10 + [3.] * 10 + [4.] * 10))
    bins = stats().quintiles(frame.factor)
    assert bins.iloc[:60].nunique() == 1


def test_benchmark_includes_non_n_stocks_and_missing_returns_are_not_zero():
    date = pd.Timestamp("2024-01-01")
    frame = pd.DataFrame(dict(date=[date] * 3, threshold=.05,
                              status=["valid", "valid", "non_rising_highs"], factor=[.1, -.1, np.nan],
                              return_5=[.1, np.nan, -.1], mae_5=[-.02, np.nan, -.2]))
    out = stats().event_statistics(frame, horizons=(5,))
    r = out[out.group == "all_n"].iloc[0]
    assert r.mean_return == pytest.approx(.1)
    assert r.mean_excess == pytest.approx(.1)
    assert r.win_rate == 1
    assert r.n_input == 2 and r.n_labeled == 1


def test_adjustment_events_only_apply_from_effective_day():
    text = 'var sz000001hfq={"total":2,"data":[{"d":"2024-01-03","f":"2"},{"d":"1900-01-01","f":"1"}]}\n/* comment */'
    events = data().parse_adjustment_events(text, "000001.SZ")
    prices = pd.DataFrame(dict(code="000001.SZ", date=pd.bdate_range("2024-01-01", periods=4)))
    # Parquet daily timestamps use milliseconds; provider JSON uses nanoseconds.
    prices["date"] = prices.date.astype("datetime64[ms]")
    expanded = data().expand_adjustment_events(prices, events)
    assert expanded.adj_factor.tolist() == [1, 1, 2, 2]
    with pytest.raises(ValueError, match="复权"):
        data().parse_adjustment_events(text.replace('"total":2', '"total":3'), "000001.SZ")


def test_small_research_keeps_exact_event_dates_and_writes_outputs(tmp_path):
    from python.tests.backtest.test_n_pullback import pattern
    module = importlib.import_module("python.research.stock.n_pullback_amv_entry.study")
    daily = pattern()
    observation_date = daily.date.iloc[-1]
    extra_dates = pd.bdate_range(observation_date + pd.Timedelta(days=1), periods=20)
    tail = pd.DataFrame(dict(date=extra_dates, open=13., high=14., low=12., close=14.))
    daily = pd.concat([daily, tail], ignore_index=True)
    daily["code"] = "000001.SZ"
    daily["valid"] = True
    source = tmp_path / "source"
    source.mkdir()
    (source / "run_manifest.json").write_text(json.dumps(dict(task_id="amv_winning_defensive", status="complete")))
    pd.DataFrame(dict(date=[int(observation_date.strftime("%Y%m%d"))],
                      code=["512100.SH"], side=["buy"])).to_csv(source / "trades_601288.SH.csv", index=False)
    out = tmp_path / "out"
    module.run_research(out, start_date="20180101", end_date="20251231", source_run=source,
                        prepared_daily=daily, calendar=pd.DatetimeIndex(daily.date),
                        bootstrap_repeats=20, render=True)
    rows = pd.read_parquet(out / "observations.parquet")
    assert rows.date.unique().tolist() == [observation_date]
    original = rows[rows.threshold == .05].iloc[0]
    assert original.factor == pytest.approx(13 / 12 - 1)
    assert original.return_5 == pytest.approx(14 / 13 - 1)
    assert (out / "report.md").is_file()
    assert (out / "summary.csv").is_file()
    assert (out / "figures/group_excess_returns.png").is_file()
    assert len(list((out / "figures").glob("structure_*.png"))) == 1


def test_research_task_is_registered_with_its_own_handler_and_zero_fees():
    from python.task_registry import TASKS
    task = TASKS[("research", "n_pullback_amv_entry")]
    assert task.kind == "research"
    assert task.default_fees.commission_rate == 0
    assert task.execution_mode == "research_next_market_open_adjusted_price"


def test_prepared_cache_rejects_unknown_preparation_version(tmp_path, monkeypatch):
    module = importlib.import_module("python.research.stock.n_pullback_amv_entry.study")
    events = pd.DatetimeIndex(["2024-01-02"])
    (tmp_path / "prepared.parquet").write_bytes(b"old-cache")
    (tmp_path / "preparation_manifest.json").write_text(json.dumps({
        "events": ["2024-01-02"], "prepared_sha256": data().sha256(tmp_path / "prepared.parquet")}))
    monkeypatch.setattr(module, "prepare_data", lambda *args: "rebuilt")
    assert module.load_prepared(events, tmp_path, tmp_path) == "rebuilt"


def test_research_rejects_completely_missing_frozen_event(tmp_path, monkeypatch):
    module = importlib.import_module("python.research.stock.n_pullback_amv_entry.study")
    events = pd.DatetimeIndex(["2024-01-02", "2024-01-03"])
    monkeypatch.setattr(module, "load_events", lambda *args: events)
    monkeypatch.setattr(module, "build_observations", lambda *args: pd.DataFrame({
        "date": [events[0]] * 3, "threshold": module.THRESHOLDS}))
    with pytest.raises(ValueError, match="缺失完整开仓日"):
        module.run_research(tmp_path / "out", prepared_daily=pd.DataFrame({
            "code": ["000001.SZ"], "date": [events[0]]}), calendar=events, render=False)


def test_stock_universe_excludes_cdr_without_dropping_star_or_beijing():
    frame = pd.DataFrame({'code': ['689009.SH', '688001.SH', '600000.SH', '920001.BJ', '000001.SZ']})
    result = data().stock_universe(frame)
    assert result.code.tolist() == ['688001.SH', '600000.SH', '920001.BJ', '000001.SZ']
