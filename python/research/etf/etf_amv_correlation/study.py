"""Rank ETFs by stable positive daily-return correlation with 0AMV."""
from __future__ import annotations

from python.research.date_scope import scoped_ranges

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from python.research.etf.amv_buy_etf_cross_section.study import aggregate_intraday_etf
from python.research.amv.amv_quantile_window_impact.study import spearman_correlation
from python.factor_research.data import load_amv_csv


SAMPLES = {
    "train": ("2015-01-01", "2023-12-31"),
    "oos": ("2024-01-01", "2025-12-31"),
    "all": (None, None),
}
DEFAULT_MIN_OBSERVATIONS = 120
DEFAULT_ROLLING_WINDOW = 60


def _daily_returns(frame: pd.DataFrame, value_name: str) -> pd.DataFrame:
    """Normalize a close series and calculate close-to-close daily returns."""
    missing = {"date", "close"}.difference(frame.columns)
    if missing:
        raise ValueError(f"数据缺少列: {', '.join(sorted(missing))}")
    result = frame.loc[:, ["date", "close"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result["close"] = pd.to_numeric(result["close"], errors="raise")
    result = result.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    if (result["close"] <= 0).any():
        raise ValueError("收盘价必须为正")
    result[value_name] = result["close"].pct_change()
    return result.loc[:, ["date", value_name]]


def correlate_daily_returns(
    code: str,
    amv: pd.DataFrame,
    etf: pd.DataFrame,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> dict[str, object]:
    """Measure same-day 0AMV and ETF return correlation on their date intersection."""
    if rolling_window < 2 or min_observations < 2:
        raise ValueError("rolling_window 和 min_observations 均必须至少为 2")
    amv_returns = _daily_returns(amv, "amv_return")
    etf_returns = _daily_returns(etf, "etf_return")
    paired = amv_returns.merge(etf_returns, on="date", how="inner").dropna().sort_values("date")
    count = len(paired)
    metrics: dict[str, object] = {"code": code, "overlap_count": int(count)}
    if count < min_observations:
        return metrics | {
            "pearson_corr": np.nan,
            "spearman_corr": np.nan,
            "rolling_corr_median": np.nan,
            "rolling_positive_share_pct": np.nan,
        }
    rolling = paired["amv_return"].rolling(rolling_window, min_periods=rolling_window).corr(paired["etf_return"]).dropna()
    pearson = paired["amv_return"].corr(paired["etf_return"], method="pearson")
    spearman = spearman_correlation(paired["amv_return"], paired["etf_return"])
    return metrics | {
        "pearson_corr": float(round(pearson, 12)),
        "spearman_corr": float(round(spearman, 12)),
        "rolling_corr_median": float(round(rolling.median(), 12)) if not rolling.empty else np.nan,
        "rolling_positive_share_pct": float(round((rolling > 0).mean() * 100, 12)) if not rolling.empty else np.nan,
    }


def rank_stable_positive_drivers(
    stage_summary: pd.DataFrame,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> pd.DataFrame:
    """Keep ETFs positively correlated in both TRAIN and OOS and rank worst-stage strength."""
    required = {
        "code", "stage", "overlap_count", "pearson_corr", "spearman_corr",
        "rolling_corr_median", "rolling_positive_share_pct",
    }
    missing = required.difference(stage_summary.columns)
    if missing:
        raise ValueError(f"阶段相关性汇总缺少列: {', '.join(sorted(missing))}")
    train = stage_summary.loc[stage_summary["stage"] == "train"].set_index("code")
    oos = stage_summary.loc[stage_summary["stage"] == "oos"].set_index("code")
    shared = train.join(oos, how="inner", lsuffix="_train", rsuffix="_oos")
    eligible = shared.loc[
        (shared["overlap_count_train"] >= min_observations)
        & (shared["overlap_count_oos"] >= min_observations)
        & (shared["pearson_corr_train"] > 0)
        & (shared["pearson_corr_oos"] > 0)
    ].copy()
    if eligible.empty:
        return pd.DataFrame(columns=["code", "stable_pearson_score"])
    eligible["stable_pearson_score"] = eligible[["pearson_corr_train", "pearson_corr_oos"]].min(axis=1)
    eligible["mean_spearman_corr"] = eligible[["spearman_corr_train", "spearman_corr_oos"]].mean(axis=1)
    eligible["min_rolling_positive_share_pct"] = eligible[
        ["rolling_positive_share_pct_train", "rolling_positive_share_pct_oos"]
    ].min(axis=1)
    result = eligible.reset_index()
    result["name"] = result["name_train"] if "name_train" in result else result["code"]
    return result.sort_values(
        ["stable_pearson_score", "mean_spearman_corr", "code"],
        ascending=[False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)


def _stage_frame(frame: pd.DataFrame, bounds: tuple[str | None, str | None]) -> pd.DataFrame:
    start, end = bounds
    result = frame
    if start is not None:
        result = result.loc[pd.to_datetime(result["date"]) >= pd.Timestamp(start)]
    if end is not None:
        result = result.loc[pd.to_datetime(result["date"]) <= pd.Timestamp(end)]
    return result.copy()


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    rows = frame.fillna("").astype(str).itertuples(index=False, name=None)
    return "\n".join([
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ])


def run_research(
    amv_path: Path,
    etf_dir: Path,
    output_dir: Path,
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Analyze every readable ETF CSV and write stage metrics plus a stable-driver ranking."""
    amv = load_amv_csv(amv_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(etf_dir.glob("*.csv")):
        code = path.stem
        try:
            raw = pd.read_csv(path)
            name = str(raw["名称"].dropna().iloc[0]) if "名称" in raw and raw["名称"].notna().any() else code
            daily = aggregate_intraday_etf(raw)
            for stage, bounds in scoped_ranges(SAMPLES).items():
                metrics.append(correlate_daily_returns(
                    code, _stage_frame(amv, bounds), _stage_frame(daily, bounds),
                    rolling_window=rolling_window, min_observations=min_observations,
                ) | {"name": name, "stage": stage})
        except (OSError, ValueError, pd.errors.ParserError) as error:
            skipped.append({"code": code, "reason": str(error)})
    stage_summary = pd.DataFrame(metrics)
    ranking = rank_stable_positive_drivers(stage_summary, min_observations=min_observations)
    stage_summary.to_csv(output_dir / "stage_correlation_summary.csv", index=False, encoding="utf-8-sig")
    ranking.to_csv(output_dir / "stable_positive_driver_ranking.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(skipped).to_csv(output_dir / "skipped_etfs.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "factor": "same-session close-to-close daily return correlation with 0AMV",
        "stages": SAMPLES,
        "minimum_observations_per_stage": min_observations,
        "rolling_window": rolling_window,
        "ranking": "positive Pearson correlation in both TRAIN and OOS; score is min(train, oos) Pearson",
        "etf_file_count": len(list(etf_dir.glob("*.csv"))),
        "skipped_etf_count": len(skipped),
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    report = (
        "# ETF 对 0AMV 的稳定同步驱动研究\n\n"
        "相关性衡量 ETF 与 0AMV 同一交易日的收盘到收盘收益同步程度；它不证明因果，也不代表 0AMV 领先 ETF。"
        "排名要求 TRAIN、OOS 的 Pearson 均为正，并以两段中较弱的一段作为稳定性分数。\n\n"
        "## 稳定正相关 ETF 前 30\n\n"
        + _markdown_table(ranking.head(30).round(4)) + "\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return stage_summary, ranking


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf-dir", type=Path, default=Path("data/backtest_data/ETF_60min_2005_2025"))
    parser.add_argument("--output", type=Path, default=Path("data/factor_research_runs/etf_amv_correlation"))
    parser.add_argument("--min-observations", type=int, default=DEFAULT_MIN_OBSERVATIONS)
    parser.add_argument("--rolling-window", type=int, default=DEFAULT_ROLLING_WINDOW)
    args = parser.parse_args()
    _, ranking = run_research(args.amv, args.etf_dir, args.output, args.min_observations, args.rolling_window)
    print(ranking.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
