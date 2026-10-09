import pandas as pd
import pytest

import python.research.etf.etf_amv_correlation.study as amv_correlation
from python.research.etf.etf_amv_correlation.study import (
    correlate_daily_returns,
    rank_stable_positive_drivers,
    run_research,
)


def test_correlate_daily_returns_aligns_common_dates_and_reports_perfect_positive_driver():
    dates = pd.date_range("2024-01-01", periods=6, freq="B")
    amv = pd.DataFrame({"date": dates, "close": [100.0, 110.0, 104.5, 125.4, 121.638, 145.9656]})
    etf = pd.DataFrame({"date": dates, "close": [10.0, 11.0, 10.45, 12.54, 12.1638, 14.59656]})

    result = correlate_daily_returns("TEST", amv, etf, rolling_window=3, min_observations=3)

    assert result["code"] == "TEST"
    assert result["overlap_count"] == 5
    assert result["pearson_corr"] == pytest.approx(1.0)
    assert result["spearman_corr"] == pytest.approx(1.0)
    assert result["rolling_corr_median"] == pytest.approx(1.0)
    assert result["rolling_positive_share_pct"] == 100.0


def test_rank_stable_positive_drivers_requires_positive_train_and_oos_correlations():
    stage_summary = pd.DataFrame({
        "code": ["A", "A", "B", "B", "C", "C"],
        "stage": ["train", "oos"] * 3,
        "overlap_count": [300, 200, 300, 200, 300, 200],
        "pearson_corr": [0.80, 0.60, 0.90, -0.10, 0.70, 0.50],
        "spearman_corr": [0.70, 0.50, 0.80, -0.20, 0.60, 0.40],
        "rolling_corr_median": [0.75, 0.55, 0.85, -0.15, 0.65, 0.45],
        "rolling_positive_share_pct": [90.0, 80.0, 95.0, 20.0, 85.0, 75.0],
    })

    ranked = rank_stable_positive_drivers(stage_summary, min_observations=120)

    assert ranked["code"].tolist() == ["A", "C"]
    assert ranked.loc[ranked["code"] == "A", "stable_pearson_score"].item() == 0.60
    assert ranked.loc[ranked["code"] == "C", "stable_pearson_score"].item() == 0.50


def test_run_research_keeps_etf_names_in_the_stable_driver_ranking(tmp_path, monkeypatch):
    dates = pd.date_range("2024-01-01", periods=20, freq="B")
    monkeypatch.setattr(amv_correlation, "SAMPLES", {
        "train": (str(dates[0].date()), str(dates[9].date())),
        "oos": (str(dates[10].date()), str(dates[-1].date())),
        "all": (None, None),
    })
    amv_path = tmp_path / "amv.csv"
    returns = [0.01, -0.02, 0.03, -0.01, 0.02] * 4
    closes = [100.0]
    for value in returns[1:]:
        closes.append(closes[-1] * (1.0 + value))
    pd.DataFrame({"date": dates, "close": closes}).to_csv(amv_path, index=False)
    etf_dir = tmp_path / "etfs"
    etf_dir.mkdir()
    for code, name in (("AAA.SH", "测试正相关"), ("BBB.SH", "测试负相关")):
        close = [value / 10.0 for value in closes]
        if code == "BBB.SH":
            close = [10.0]
            for value in returns[1:]:
                close.append(close[-1] * (1.0 - value))
        pd.DataFrame({
            "时间": dates, "代码": code, "名称": name,
            "开盘价": close, "最高价": close, "最低价": close, "收盘价": close,
            "成交量": [100.0] * len(dates), "成交额": [1_000.0] * len(dates),
        }).to_csv(etf_dir / f"{code}.csv", index=False)

    _, ranking = run_research(amv_path, etf_dir, tmp_path / "output", min_observations=3, rolling_window=3)

    assert ranking[["code", "name"]].to_dict("records") == [{"code": "AAA.SH", "name": "测试正相关"}]
    assert (tmp_path / "output" / "stable_positive_driver_ranking.csv").exists()
