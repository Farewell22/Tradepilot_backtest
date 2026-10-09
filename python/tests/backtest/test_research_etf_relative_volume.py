import numpy as np
import pandas as pd

import python.research.etf.etf_relative_volume.study as relative_volume

from python.research.etf.etf_relative_volume.study import (
    HORIZONS,
    add_relative_volume_features,
    assign_cross_section_quintiles,
    attach_forward_returns,
    build_observations,
    summarize_factor,
)


def test_relative_volume_features_use_non_overlapping_short_and_medium_baselines():
    daily = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=110, freq="B"),
        "close": [100.0] * 110,
        "volume": [100.0] * 80 + [200.0] * 23 + [400.0] * 7,
    })

    featured = add_relative_volume_features(daily)

    assert featured.iloc[-1]["volume_ratio_7_20"] == 2.0
    assert np.isclose(featured.iloc[-1]["volume_ratio_30_80"], (23 * 200.0 + 7 * 400.0) / 30 / 100.0)


def test_cross_section_quintiles_keep_only_trending_etfs_and_rank_each_factor_independently():
    observations = pd.DataFrame({
        "date": pd.to_datetime(["2024-06-03"] * 6),
        "code": list("ABCDEF"),
        "trend_up": [True, True, True, True, True, False],
        "volume_ratio_7_20": [1.0, 2.0, 3.0, 4.0, 5.0, 99.0],
        "volume_ratio_30_80": [5.0, 4.0, 3.0, 2.0, 1.0, 99.0],
    })

    grouped = assign_cross_section_quintiles(observations)

    assert grouped.loc[grouped["code"] == "A", "volume_ratio_7_20_quintile"].item() == "Q1"
    assert grouped.loc[grouped["code"] == "E", "volume_ratio_7_20_quintile"].item() == "Q5"
    assert grouped.loc[grouped["code"] == "A", "volume_ratio_30_80_quintile"].item() == "Q5"
    assert grouped.loc[grouped["code"] == "F", "volume_ratio_7_20_quintile"].isna().item()


def test_cross_section_quintiles_break_equal_factor_ties_by_code():
    observations = pd.DataFrame({
        "date": pd.to_datetime(["2024-06-03"] * 10),
        "code": ["Z", "B", "A", "C", "D", "E", "F", "G", "H", "I"],
        "trend_up": [True] * 10,
        "volume_ratio_7_20": [0.0, 1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        "volume_ratio_30_80": [0.0, 1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
    })

    grouped = assign_cross_section_quintiles(observations)

    assert grouped.loc[grouped["code"] == "A", "volume_ratio_7_20_quintile"].item() == "Q1"
    assert grouped.loc[grouped["code"] == "B", "volume_ratio_7_20_quintile"].item() == "Q2"


def test_relative_volume_features_do_not_use_data_after_the_signal_date():
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    original = pd.DataFrame({"date": dates, "close": np.arange(100.0, 220.0), "volume": np.arange(100.0, 220.0)})
    changed = original.copy()
    changed.loc[101:, ["close", "volume"]] = 9_999.0

    before = add_relative_volume_features(original)
    after = add_relative_volume_features(changed)

    columns = ["volume_ratio_7_20", "volume_ratio_30_80", "ma20", "trend_up"]
    pd.testing.assert_frame_equal(before.loc[:100, columns], after.loc[:100, columns])


def test_forward_returns_enter_on_next_session_and_support_the_60_day_horizon():
    events = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"])})
    prices = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=62, freq="B"),
        "open": np.arange(10.0, 72.0),
        "close": np.arange(10.5, 72.5),
    })

    labels = attach_forward_returns(events, prices, horizons=HORIZONS)

    assert labels.loc[0, "entry_date"] == pd.Timestamp("2024-01-02")
    assert labels.loc[0, "forward_return_5_pct"] == (prices.loc[5, "close"] / prices.loc[1, "open"] - 1.0) * 100.0
    assert labels.loc[0, "forward_return_60_pct"] == (prices.loc[60, "close"] / prices.loc[1, "open"] - 1.0) * 100.0


def test_build_observations_separates_full_and_buy_point_cross_sections_and_adds_excess_labels():
    dates = pd.date_range("2024-01-01", periods=180, freq="B")
    universe = {}
    for index, code in enumerate("ABCDE"):
        universe[code] = pd.DataFrame({
            "date": dates,
            "open": 10.0 + index + np.arange(len(dates)) * 0.01,
            "close": 10.2 + index + np.arange(len(dates)) * 0.01,
            "volume": [100.0] * 100 + [100.0 + index * 10.0] * 50 + [200.0 + index * 10.0] * 30,
        })
    reference = pd.DataFrame({
        "date": dates,
        "open": [10.0] * len(dates),
        "close": [10.5] * len(dates),
    })
    events = pd.DataFrame({
        "date": [dates[115], dates[115]],
        "sample_type": ["full", "buy_point"],
    })

    observations = build_observations(events, universe, reference)

    assert set(observations["sample_type"]) == {"full", "buy_point"}
    assert observations.groupby("sample_type")["volume_ratio_7_20_quintile"].count().to_dict() == {"buy_point": 5, "full": 5}
    assert observations["reference_forward_return_60_pct"].notna().all()
    assert np.allclose(
        observations["excess_return_5_pct"],
        observations["forward_return_5_pct"] - observations["reference_forward_return_5_pct"],
    )


def test_summarize_factor_reports_q5_minus_q1_and_daily_spearman_ic():
    observations = pd.DataFrame({
        "date": pd.to_datetime(["2024-06-03"] * 5),
        "sample_type": ["full"] * 5,
        "code": list("ABCDE"),
        "volume_ratio_7_20": [1.0, 2.0, 3.0, 4.0, 5.0],
        "volume_ratio_7_20_quintile": ["Q1", "Q2", "Q3", "Q4", "Q5"],
        "forward_return_5_pct": [1.0, 2.0, 3.0, 4.0, 5.0],
        "excess_return_5_pct": [0.0, 1.0, 2.0, 3.0, 4.0],
    })

    summary = summarize_factor(observations, "volume_ratio_7_20", "dynamic", "all", horizons=(5,))

    spread = summary.loc[summary["quintile"] == "Q5-Q1"].iloc[0]
    ic = summary.loc[summary["quintile"] == "IC/top1"].iloc[0]
    assert spread["mean_return_pct"] == 4.0
    assert spread["mean_excess_return_pct"] == 4.0
    assert ic["mean_spearman_ic"] == 1.0


def test_summarize_factor_calculates_ic_and_top1_only_from_trend_eligible_quintiles():
    eligible = pd.DataFrame({
        "date": pd.to_datetime(["2024-06-03"] * 5), "sample_type": ["full"] * 5,
        "code": list("ABCDE"), "volume_ratio_7_20": [1., 2., 3., 4., 5.],
        "volume_ratio_7_20_quintile": ["Q1", "Q2", "Q3", "Q4", "Q5"],
        "forward_return_5_pct": [1., 2., 3., 4., 5.], "excess_return_5_pct": [0., 1., 2., 3., 4.],
    })
    ineligible = pd.DataFrame({
        "date": pd.to_datetime(["2024-06-03"] * 5), "sample_type": ["full"] * 5,
        "code": list("VWXYZ"), "volume_ratio_7_20": [6., 7., 8., 9., 10.],
        "volume_ratio_7_20_quintile": [pd.NA] * 5,
        "forward_return_5_pct": [5., 4., 3., 2., 1.], "excess_return_5_pct": [4., 3., 2., 1., 0.],
    })

    summary = summarize_factor(pd.concat([eligible, ineligible], ignore_index=True), "volume_ratio_7_20", "dynamic", "all", horizons=(5,))

    ic = summary.loc[summary["quintile"] == "IC/top1"].iloc[0]
    assert ic["event_count"] == 1
    assert ic["mean_spearman_ic"] == 1.0
    assert ic["mean_return_pct"] == 5.0


def test_run_research_writes_dynamic_and_common_outputs_for_full_and_buy_point_samples(tmp_path, monkeypatch):
    codes = {code: code for code in "ABCDE"}
    monkeypatch.setattr(relative_volume, "CANDIDATES", codes, raising=False)
    dates = pd.date_range("2024-01-01", periods=180, freq="B")
    etf_dir = tmp_path / "etfs"
    etf_dir.mkdir()
    for index, code in enumerate(codes):
        pd.DataFrame({
            "date": dates, "open": 10.0 + index + np.arange(len(dates)) * 0.01,
            "high": 11.0 + index + np.arange(len(dates)) * 0.01,
            "low": 9.0 + index + np.arange(len(dates)) * 0.01,
            "close": 10.2 + index + np.arange(len(dates)) * 0.01,
            "volume": [100.0] * 100 + [100.0 + index * 10.0] * 50 + [200.0 + index * 10.0] * 30,
            "amount": [1_000.0] * len(dates),
        }).to_csv(etf_dir / f"{code}.csv", index=False)
    reference_path = etf_dir / "REF.csv"
    pd.DataFrame({
        "date": dates, "open": [10.0] * len(dates), "high": [11.0] * len(dates),
        "low": [9.0] * len(dates), "close": [10.5] * len(dates), "volume": [100.0] * len(dates),
        "amount": [1_000.0] * len(dates),
    }).to_csv(reference_path, index=False)
    amv_path = tmp_path / "amv.csv"
    pd.DataFrame({"date": dates, "close": np.arange(1.0, len(dates) + 1.0)}).to_csv(amv_path, index=False)
    monkeypatch.setattr(
        relative_volume,
        "generate_buy_signals",
        lambda _: pd.DataFrame({"date": [dates[115]], "signal_type": ["class_2"]}),
        raising=False,
    )

    output = tmp_path / "output"
    summary = relative_volume.run_research(amv_path, etf_dir, reference_path, output)

    assert {"full", "buy_point"}.issubset(summary["sample_type"])
    assert set(summary["universe"]) == {"dynamic", "common"}
    assert (output / "observations_dynamic_all.csv").exists()
    assert (output / "factor_summary.csv").exists()
    assert (output / "metadata.json").exists()
    assert (output / "report.md").exists()
