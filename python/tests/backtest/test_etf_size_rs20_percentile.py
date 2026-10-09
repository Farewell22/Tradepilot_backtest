"""Hand-calculated contracts for style strength and forward-return research."""
import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        pytest.fail(f"Planned research module is missing: {name}")


def factors():
    return module("python.factors.relative_strength")


def study():
    return module("python.research.etf.etf_size_rs20_percentile.study")


def test_cash_dividend_and_share_consolidation_preserve_wealth():
    dates = pd.bdate_range("2020-01-01", periods=5)
    prices = pd.DataFrame({"date": dates, "close": [10, 9, 18, 18, 19.8]})
    actions = pd.DataFrame({"price_effective_date": dates[[1, 2]],
                            "cash_per_share": [1.0, 0.0], "share_ratio": [1.0, 0.5]})
    actual = factors().total_return_index(prices, actions)
    np.testing.assert_allclose(actual, [100, 100, 100, 100, 110])


def test_relative_strength_is_difference_of_returns_not_price_ratio():
    dates = pd.bdate_range("2020-01-01", periods=3)
    small = pd.Series([100, 110, 120], index=dates)
    large = pd.Series([100, 100, 105], index=dates)
    result = factors().relative_strength(small, large, lookback=2)
    assert result.iloc[:2].isna().all()
    assert result.iloc[2] == pytest.approx(0.15)


def test_percentile_uses_only_trailing_window_and_midpoint_ties():
    result = factors().rolling_percentile(pd.Series([1., 2., 3., 2., 2.]), window=3)
    # Both final windows are [2, 3, 2] or [3, 2, 2]: zero lower and two ties.
    np.testing.assert_allclose(result, [np.nan, np.nan, 100 * 2.5 / 3, 100 / 3, 100 / 3], equal_nan=True)
    np.testing.assert_allclose(factors().rolling_percentile(pd.Series([0.] * 5), 3).dropna(), 50)


def test_future_rows_and_future_actions_cannot_rewrite_historical_factors():
    dates = pd.bdate_range("2020-01-01", periods=140)
    prices = pd.DataFrame({"date": dates, "close": np.arange(100., 240.)})
    actions = pd.DataFrame({"price_effective_date": [dates[-1]], "cash_per_share": [1.], "share_ratio": [1.]})
    old = factors().total_return_index(prices.iloc[:125], actions)
    new = factors().total_return_index(prices, actions)
    pd.testing.assert_series_equal(old, new.iloc[:125])
    pd.testing.assert_series_equal(factors().rolling_percentile(old.pct_change(20)),
                                   factors().rolling_percentile(new.pct_change(20)).iloc[:125])


def test_close_to_close_labels_have_independent_missing_tails():
    prices = pd.Series(np.arange(100., 171.), index=pd.bdate_range("2020-01-01", periods=71))
    five = factors().forward_return(prices, 5)
    sixty = factors().forward_return(prices, 60)
    assert five.iloc[0] == pytest.approx(0.05)
    assert sixty.iloc[0] == pytest.approx(0.60)
    assert five.isna().sum() == 5
    assert sixty.isna().sum() == 60


def test_factor_rejects_misaligned_dates_and_nonfinite_prices():
    dates = pd.bdate_range("2020-01-01", periods=4)
    with pytest.raises(ValueError, match="日期"):
        factors().relative_strength(pd.Series([1.] * 4, dates), pd.Series([1.] * 3, dates[:3]))
    with pytest.raises(ValueError, match="价格"):
        factors().total_return_index(pd.DataFrame({"date": dates, "close": [1, 2, np.inf, 3]}), pd.DataFrame())


def intraday(dates, closes):
    return pd.DataFrame([{"时间": f"{date.date()} {time}", "开盘价": close, "收盘价": close,
                          "最高价": close, "最低价": close, "成交量": 10}
                         for date, close in zip(dates, closes)
                         for time in ("10:30:00", "11:30:00", "14:00:00", "15:00:00")])


def test_aggregation_sorts_actual_timestamps_and_rejects_incomplete_days():
    raw = intraday(pd.bdate_range("2020-01-01", periods=2), [10, 20])
    raw.loc[3, "收盘价"] = 11
    raw.loc[3, "最高价"] = 11
    result = study().daily_prices(raw.iloc[::-1])
    assert result.iloc[0].close == 11
    with pytest.raises(ValueError, match="4"):
        study().daily_prices(raw.iloc[:-1])


def test_unknown_calendar_gap_is_rejected_instead_of_compressing_time():
    dates = pd.bdate_range("2020-01-01", periods=10)
    frame = pd.DataFrame({"date": dates, "close": 10., "volume": 100.})
    with pytest.raises(ValueError, match="日期"):
        study().align_daily({"512100.SH": frame.drop(index=4), "510050.SH": frame})


@pytest.mark.parametrize("missing", [0, -1])
def test_missing_boundary_session_cannot_silently_shorten_calendar(missing):
    frame = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=5), "close": 10., "volume": 100.})
    with pytest.raises(ValueError, match="日期"):
        study().align_daily({"512100.SH": frame.drop(index=frame.index[missing]), "510050.SH": frame})


def test_four_bars_without_actual_session_close_are_rejected():
    raw = intraday(pd.bdate_range("2020-01-01", periods=1), [10])
    raw.loc[3, "时间"] = "2020-01-01 14:30:00"
    with pytest.raises(ValueError, match="时段"):
        study().daily_prices(raw)


def test_known_suspension_is_removed_before_applying_post_merger_quote_ratio():
    dates = pd.to_datetime(["2022-09-01", "2022-09-02", "2022-09-05"])
    small = pd.DataFrame({"date": dates, "close": [1., 1., 2.], "volume": [1, 0, 1]})
    large = pd.DataFrame({"date": dates, "close": [1., 1., 1.], "volume": 1})
    aligned, audit = study().align_daily({"512100.SH": small, "510050.SH": large})
    assert len(aligned["512100.SH"]) == 2
    assert audit["excluded_common_dates"] == ["2022-09-02"]
    action = pd.DataFrame({"price_effective_date": ["2022-09-05"], "cash_per_share": [0], "share_ratio": [.5]})
    np.testing.assert_allclose(factors().total_return_index(aligned["512100.SH"], action), [100, 100])


def test_observation_scope_keeps_warmup_and_labels_outside_requested_end():
    dates = pd.bdate_range("2019-01-01", periods=180)
    small = pd.Series(np.arange(100., 280.), dates)
    large = pd.Series(100., dates)
    start, end = dates[125], dates[130]
    rows = study().build_observations(small, large, str(start.date()), str(end.date()))
    assert len(rows) == 6
    assert rows.rs20_percentile.notna().all()
    assert rows.return_1000_5d.notna().all()
    assert rows.return_1000_60d.isna().all()
    assert rows.iloc[0].return_1000_5d == pytest.approx(230 / 225 - 1)
    assert rows.iloc[0].spread_5d == pytest.approx(rows.iloc[0].return_1000_5d)


def test_empty_deciles_are_kept_and_constant_factor_ic_is_missing():
    rows = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=4), "session_index": range(4),
                         "rs20_percentile": 50., "percentile_bin": 6,
                         "return_1000_5d": [.1, .2, np.nan, .3], "return_50_5d": 0.,
                         "spread_5d": [.1, .2, np.nan, .3]})
    summary, effects, phases = study().analyze(rows, horizons=(5,), bootstrap_repeats=10)
    selected = summary[(summary.stage == "all") & (summary.target == "1000")]
    assert len(selected) == 10
    assert selected.loc[selected.percentile_bin.eq(6), "labeled"].iloc[0] == 3
    assert selected.loc[selected.percentile_bin.eq(6), "mean_pct"].iloc[0] == pytest.approx(20.)
    assert effects.spearman_ic.isna().all()
    assert effects.ic_ci_low.isna().all()
    assert set(phases.phase) == set(range(5))


def test_block_bootstrap_is_deterministic_and_preserves_calendar_gaps():
    n = 300
    frame = pd.DataFrame({"rs20_percentile": np.tile(np.arange(100), 3) + .5,
                         "percentile_bin": np.tile(np.arange(100) // 10 + 1, 3),
                         "target": np.tile(np.arange(100), 3) / 1000})
    frame.loc[150:155, "target"] = np.nan
    a = study().bootstrap_effects(frame, "target", repeats=25)
    b = study().bootstrap_effects(frame, "target", repeats=25)
    assert a == b
    assert a["ic_ci_low"] == pytest.approx(1.)
    assert a["ic_ci_high"] == pytest.approx(1.)
    assert a["spread_ci_low_pct"] > 0


def test_registry_is_independent_of_amv_and_uses_close_labels():
    from python.task_registry import TASKS
    key = ("research", "etf_size_rs20_percentile")
    assert key in TASKS
    task = TASKS[key]
    assert task.default_start_date == "20200101"
    assert task.execution_mode == "research_close_to_close_total_return"
    assert not any("0AMV" in str(path) for path in task.data_sources)
    assert not task.supports_fee_override


def test_runner_emits_reproducible_artifacts_and_filters_actual_dates(tmp_path):
    directory = tmp_path / "input"
    directory.mkdir()
    dates = pd.bdate_range("2020-01-01", periods=280)
    for code, values in (("512100.SH", np.arange(100., 380.)), ("510050.SH", np.full(280, 100.))):
        # Bad vendor history before audited warmup must not block the study.
        raw = pd.concat([intraday(pd.to_datetime(["2006-01-09"]), [0]), intraday(dates, values)])
        raw.to_csv(directory / f"{code}.csv", index=False)
    actions = tmp_path / "actions.csv"
    pd.DataFrame(columns=["code", "kind", "record_date", "ex_date", "pay_date", "price_effective_date",
                          "cash_per_share", "share_ratio", "source_url"]).to_csv(actions, index=False)
    audit = tmp_path / "audit.json"
    audit.write_text('{"coverage_start":"2020-01-01","coverage_end":"2022-12-31"}')
    out = tmp_path / "output"
    study().run_research(directory, out, start_date=str(dates[125].date()), end_date=str(dates[129].date()),
                         actions_path=actions, action_audit_path=audit, bootstrap_repeats=10)
    actual = pd.read_csv(out / "observations.csv")
    assert len(actual) == 5
    assert actual.date.min() == str(dates[125].date())
    assert actual.date.max() == str(dates[129].date())
    for file in ("summary.csv", "effects.csv", "nonoverlap.csv", "data_audit.json", "metadata.json",
                 "execution_metadata.json", "report.md", "quantile_returns.png", "annual_stability.png"):
        assert (out / file).is_file(), file
    assert (out / "inputs" / "512100.SH.csv").is_file()
    assert (out / "source_snapshot" / "python" / "factors" / "relative_strength.py").is_file()
