"""Study AMV/MA10 gap quintiles while AMV MA10 is below MA30.

The factor is ranked from Q1 (most negative gap) to Q5 (most positive
gap).  Forward 510300 returns enter at the next ETF session open.
"""
from __future__ import annotations

from python.research.date_scope import scoped_ranges

import argparse
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from python.strategies.etf_amv.strategy import normalize_etf_history
from python.factor_research.data import load_amv_csv


DEFAULT_HORIZONS = (3, 5, 10, 20)
SAMPLES = {
    "train": ("2015-01-01", "2023-12-31"),
    "oos": ("2024-01-01", "2025-12-31"),
}


def compute_amv_gap_factor(amv: pd.DataFrame) -> pd.DataFrame:
    """Return dates in the MA10 < MA30 regime with their signed MA10 gap."""
    required = {"date", "close"}
    missing = required.difference(amv.columns)
    if missing:
        raise ValueError(f"0AMV 数据缺少列: {', '.join(sorted(missing))}")
    result = amv.loc[:, ["date", "close"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result["close"] = pd.to_numeric(result["close"], errors="raise")
    result = result.sort_values("date").reset_index(drop=True)
    if result["date"].duplicated().any() or (result["close"] <= 0).any():
        raise ValueError("0AMV 数据存在重复日期或非正收盘价")
    result["ma10"] = result["close"].rolling(10, min_periods=10).mean()
    result["ma30"] = result["close"].rolling(30, min_periods=30).mean()
    result["gap10"] = result["close"] / result["ma10"] - 1.0
    return result.loc[result["ma10"] < result["ma30"]].reset_index(drop=True)


def assign_gap_quintiles(frame: pd.DataFrame) -> pd.DataFrame:
    """Assign equal-count quintiles ordered by signed gap10."""
    if "gap10" not in frame.columns:
        raise ValueError("因子数据缺少 gap10 列")
    result = frame.copy()
    valid = result["gap10"].notna()
    result["quintile"] = pd.Series(pd.NA, index=result.index, dtype="string")
    if valid.sum() < 5:
        return result
    ranks = result.loc[valid, "gap10"].rank(method="first")
    groups = pd.qcut(ranks, q=5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
    result.loc[valid, "quintile"] = groups.astype("string").to_numpy()
    return result


def attach_etf_forward_returns(
    factors: pd.DataFrame,
    etf: pd.DataFrame,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    """Attach next-open to Nth-session-close ETF forward returns."""
    horizons = tuple(int(value) for value in horizons)
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("远期周期必须为正整数")
    required = {"date", "open", "close"}
    missing = required.difference(etf.columns)
    if missing:
        raise ValueError(f"ETF 数据缺少列: {', '.join(sorted(missing))}")
    prices = etf.loc[:, ["date", "open", "close"]].copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="raise").dt.normalize()
    prices["open"] = pd.to_numeric(prices["open"], errors="raise")
    prices["close"] = pd.to_numeric(prices["close"], errors="raise")
    prices = prices.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if (prices[["open", "close"]] <= 0).any().any():
        raise ValueError("ETF 开盘价和收盘价必须为正")

    result = factors.copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result = result.loc[result["date"] >= prices["date"].iloc[0]].reset_index(drop=True)
    price_dates = prices["date"].to_numpy(dtype="datetime64[ns]")
    entry_indices = price_dates.searchsorted(result["date"].to_numpy(dtype="datetime64[ns]"), side="right")
    has_entry = entry_indices < len(prices)
    result = result.loc[has_entry].copy().reset_index(drop=True)
    entry_indices = entry_indices[has_entry]
    result["entry_date"] = prices.iloc[entry_indices]["date"].to_numpy()
    result["entry_open"] = prices.iloc[entry_indices]["open"].to_numpy()
    for horizon in horizons:
        exit_indices = entry_indices + horizon - 1
        values = pd.Series(float("nan"), index=result.index, dtype="float64")
        available = exit_indices < len(prices)
        exit_closes = prices.iloc[exit_indices[available]]["close"].to_numpy()
        entry_opens = result.loc[available, "entry_open"].to_numpy()
        values.loc[available] = (exit_closes / entry_opens - 1.0) * 100.0
        result[f"forward_return_{horizon}_pct"] = values
    return result


def summarize_quintiles(observations: pd.DataFrame, stage: str, horizons: Iterable[int]) -> pd.DataFrame:
    rows: list[dict] = []
    for quintile in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        group = observations.loc[observations["quintile"] == quintile]
        row = {
            "stage": stage,
            "quintile": quintile,
            "sample_count": int(len(group)),
            "gap10_min_pct": group["gap10"].min() * 100,
            "gap10_mean_pct": group["gap10"].mean() * 100,
            "gap10_median_pct": group["gap10"].median() * 100,
            "gap10_max_pct": group["gap10"].max() * 100,
        }
        for horizon in horizons:
            values = group[f"forward_return_{horizon}_pct"].dropna()
            row[f"return_{horizon}d_count"] = int(len(values))
            row[f"return_{horizon}d_mean_pct"] = values.mean()
            row[f"return_{horizon}d_median_pct"] = values.median()
            row[f"return_{horizon}d_win_rate_pct"] = (values > 0).mean() * 100
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_spreads(summary: pd.DataFrame, horizons: Iterable[int]) -> pd.DataFrame:
    rows: list[dict] = []
    for stage, stage_rows in summary.groupby("stage", sort=False):
        indexed = stage_rows.set_index("quintile")
        for horizon in horizons:
            means = indexed[f"return_{horizon}d_mean_pct"].reindex(["Q1", "Q2", "Q3", "Q4", "Q5"])
            group_order = pd.Series(range(1, 6), index=means.index, dtype="float64")
            mean_ranks = means.rank(method="average")
            rows.append({
                "stage": stage,
                "horizon": int(horizon),
                "q5_minus_q1_pct": means["Q5"] - means["Q1"],
                "group_spearman": group_order.corr(mean_ranks),
                "strictly_increasing": bool(means.is_monotonic_increasing),
            })
    return pd.DataFrame(rows)


def _format_report(summary: pd.DataFrame, spreads: pd.DataFrame, horizons: Iterable[int]) -> str:
    lines = [
        "# MA10低于MA30时的0AMV-MA10乖离度五分组研究",
        "",
        "因子：`gap10 = 0AMV / MA10 - 1`。仅保留 `MA10 < MA30` 的日期，",
        "按gap10从小到大等频排序：Q1为负极值，Q5为正极值。ETF收益从信号后下一交易日开盘计算。",
        "",
    ]
    for stage in ("train", "oos", "all"):
        rows = summary.loc[summary["stage"] == stage]
        if rows.empty:
            continue
        lines.extend([f"## {stage.upper()}", ""])
        headers = ["组", "样本", "gap均值"] + [f"{h}日均值/胜率" for h in horizons]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "---|" * len(headers))
        for row in rows.to_dict("records"):
            cells = [row["quintile"], str(row["sample_count"]), f'{row["gap10_mean_pct"]:+.2f}%']
            for horizon in horizons:
                cells.append(
                    f'{row[f"return_{horizon}d_mean_pct"]:+.2f}% / '
                    f'{row[f"return_{horizon}d_win_rate_pct"]:.1f}%'
                )
            lines.append("| " + " | ".join(cells) + " |")
        lines.extend(["", "Q5-Q1及单调性：", ""])
        for item in spreads.loc[spreads["stage"] == stage].to_dict("records"):
            lines.append(
                f'- {item["horizon"]}日：Q5-Q1 {item["q5_minus_q1_pct"]:+.2f}%，'
                f'组序Spearman {item["group_spearman"]:+.2f}，'
                f'严格递增：{"是" if item["strictly_increasing"] else "否"}'
            )
        lines.append("")
    lines.extend([
        "## 口径说明",
        "",
        "- 五分组在TRAIN、OOS和全样本内部各自独立排序，属于因子研究，不是可直接交易的历史滚动阈值。",
        "- 每个符合条件的日期都是一个观察值，因此远期收益可能重叠。",
        "- 中位数、各组gap边界及完整观察值见同目录CSV文件。",
        "",
    ])
    return "\n".join(lines)


def run_research(
    amv_path: Path,
    etf_path: Path,
    output_dir: Path,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    horizons = tuple(int(value) for value in horizons)
    factors = compute_amv_gap_factor(load_amv_csv(amv_path))
    raw_etf = pd.read_csv(etf_path)
    daily_etf = normalize_etf_history(raw_etf)
    observations = attach_etf_forward_returns(factors, daily_etf, horizons)

    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[pd.DataFrame] = []
    stage_ranges = scoped_ranges(SAMPLES, include_all=True)
    for stage, (start, end) in stage_ranges.items():
        stage_rows = observations.copy()
        if start is not None:
            stage_rows = stage_rows.loc[stage_rows["date"] >= pd.Timestamp(start)]
        if end is not None:
            stage_rows = stage_rows.loc[stage_rows["date"] <= pd.Timestamp(end)]
        stage_rows = assign_gap_quintiles(stage_rows.reset_index(drop=True))
        stage_rows.to_csv(output_dir / f"observations_{stage}.csv", index=False, encoding="utf-8-sig")
        summaries.append(summarize_quintiles(stage_rows, stage, horizons))

    summary = pd.concat(summaries, ignore_index=True)
    spreads = summarize_spreads(summary, horizons)
    summary.to_csv(output_dir / "quintile_summary.csv", index=False, encoding="utf-8-sig")
    spreads.to_csv(output_dir / "spread_summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(_format_report(summary, spreads, horizons), encoding="utf-8")
    metadata = {
        "amv_path": str(amv_path),
        "etf_path": str(etf_path),
        "condition": "amv_ma10 < amv_ma30",
        "factor": "amv_close / amv_ma10 - 1",
        "quintiles": "within-stage equal-count rank; Q1 lowest, Q5 highest",
        "entry": "next ETF session open",
        "horizons": list(horizons),
        "samples": SAMPLES,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary, spreads


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf", type=Path, default=Path("data/backtest_data/510300.SH.csv"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/factor_research_runs/amv_ma10_below_ma30_gap_quintiles"),
    )
    args = parser.parse_args()
    summary, spreads = run_research(args.amv, args.etf, args.output)
    print(summary.to_string(index=False))
    print("\nQ5-Q1 / monotonicity")
    print(spreads.to_string(index=False))


if __name__ == "__main__":
    main()
