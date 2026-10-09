"""Study signed 0AMV three-session momentum against 510300 forward returns."""
from __future__ import annotations

from python.research.date_scope import scoped_ranges

import argparse
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from python.strategies.etf_amv.strategy import normalize_etf_history
from python.factor_research.data import load_amv_csv


DEFAULT_HORIZONS = (3, 5, 10, 30)
SAMPLES = {
    "train": ("2015-01-01", "2023-12-31"),
    "oos": ("2024-01-01", "2025-12-31"),
}
DECILES = tuple(f"Q{index}" for index in range(1, 11))


def build_momentum_factor(amv: pd.DataFrame) -> pd.DataFrame:
    """Calculate the three-session cumulative return of positive 0AMV values."""
    missing = {"date", "close"}.difference(amv.columns)
    if missing:
        raise ValueError(f"0AMV 数据缺少列: {', '.join(sorted(missing))}")
    result = amv.loc[:, ["date", "close"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result["close"] = pd.to_numeric(result["close"], errors="raise")
    result = result.sort_values("date").reset_index(drop=True)
    if result["date"].duplicated().any() or (result["close"] <= 0).any():
        raise ValueError("0AMV 数据存在重复日期或非正收盘价")
    result["momentum_3"] = result["close"] / result["close"].shift(3) - 1.0
    return result


def attach_etf_forward_returns(
    factors: pd.DataFrame,
    etf: pd.DataFrame,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    """Keep AMV/ETF date intersections and measure next-open ETF forward returns."""
    horizons = tuple(int(value) for value in horizons)
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("远期周期必须为正整数")
    missing = {"date", "open", "close"}.difference(etf.columns)
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
    result = result.loc[result["date"].isin(prices["date"])].reset_index(drop=True)
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
        values.loc[available] = (
            prices.iloc[exit_indices[available]]["close"].to_numpy()
            / result.loc[available, "entry_open"].to_numpy()
            - 1.0
        ) * 100.0
        result[f"forward_return_{horizon}_pct"] = values
    return result


def assign_momentum_deciles(frame: pd.DataFrame) -> pd.DataFrame:
    """Assign within-sample equal-count deciles from lowest to highest momentum."""
    if "momentum_3" not in frame:
        raise ValueError("因子数据缺少 momentum_3 列")
    result = frame.copy()
    result["momentum_decile"] = pd.Series(pd.NA, index=result.index, dtype="string")
    valid = result["momentum_3"].notna()
    if valid.sum() < len(DECILES):
        return result
    ranks = result.loc[valid, "momentum_3"].rank(method="first")
    result.loc[valid, "momentum_decile"] = pd.qcut(ranks, len(DECILES), labels=DECILES).astype("string").to_numpy()
    return result


def summarize_deciles(observations: pd.DataFrame, stage: str, horizons: Iterable[int]) -> pd.DataFrame:
    rows: list[dict] = []
    for decile in DECILES:
        group = observations.loc[observations["momentum_decile"] == decile]
        row = {
            "stage": stage,
            "momentum_decile": decile,
            "sample_count": int(len(group)),
            "momentum_3_min": group["momentum_3"].min(),
            "momentum_3_mean": group["momentum_3"].mean(),
            "momentum_3_median": group["momentum_3"].median(),
            "momentum_3_max": group["momentum_3"].max(),
        }
        for horizon in horizons:
            values = group[f"forward_return_{int(horizon)}_pct"].dropna()
            row[f"return_{horizon}d_count"] = int(len(values))
            row[f"return_{horizon}d_mean_pct"] = values.mean()
            row[f"return_{horizon}d_median_pct"] = values.median()
            row[f"return_{horizon}d_win_rate_pct"] = (values > 0).mean() * 100.0
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_effects(summary: pd.DataFrame, horizons: Iterable[int]) -> pd.DataFrame:
    rows: list[dict] = []
    for stage, stage_rows in summary.groupby("stage", sort=False):
        indexed = stage_rows.set_index("momentum_decile").reindex(DECILES)
        for horizon in horizons:
            means = indexed[f"return_{int(horizon)}d_mean_pct"]
            orders = pd.Series(range(1, len(DECILES) + 1), index=DECILES, dtype="float64")
            rows.append({
                "stage": stage,
                "horizon": int(horizon),
                "q10_minus_q1_pct": means.loc["Q10"] - means.loc["Q1"],
                "group_spearman": orders.corr(means.rank(method="average")),
                "strictly_increasing": bool(means.is_monotonic_increasing),
            })
    return pd.DataFrame(rows)


def format_report(summary: pd.DataFrame, effects: pd.DataFrame, horizons: Iterable[int]) -> str:
    lines = [
        "# 0AMV 三日动量与沪深300ETF远期收益研究",
        "",
        "因子为 `(0AMV(t) - 0AMV(t-3)) / 0AMV(t-3)`，即三日累计涨跌幅。",
        "样本取0AMV与510300ETF日期交集；收益为信号后下一ETF交易日开盘至第N个交易日收盘。",
        "",
    ]
    for stage in ("train", "oos", "all"):
        rows = summary.loc[summary["stage"] == stage]
        if rows.empty:
            continue
        headers = ["组", "样本", "三日动量均值"] + [f"{h}日均值/胜率" for h in horizons]
        lines.extend([f"## {stage.upper()}", "", "| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)])
        for row in rows.to_dict("records"):
            cells = [row["momentum_decile"], str(row["sample_count"]), f'{row["momentum_3_mean"]:+.2%}']
            cells.extend(
                f'{row[f"return_{horizon}d_mean_pct"]:+.2f}% / {row[f"return_{horizon}d_win_rate_pct"]:.1f}%'
                for horizon in horizons
            )
            lines.append("| " + " | ".join(cells) + " |")
        lines.extend(["", "Q10-Q1 与单调性：", ""])
        for effect in effects.loc[effects["stage"] == stage].to_dict("records"):
            lines.append(
                f'- {effect["horizon"]}日：Q10-Q1 {effect["q10_minus_q1_pct"]:+.2f}%，'
                f'组序Spearman {effect["group_spearman"]:+.2f}，'
                f'严格递增：{"是" if effect["strictly_increasing"] else "否"}'
            )
        lines.append("")
    lines.extend([
        "## 口径说明",
        "",
        "- TRAIN、OOS及全样本各自独立等频分为十组，Q1动量最低，Q10最高。",
        "- 每个交集日期均为一个观察值，远期收益可能重叠；这不是组合净值回测。",
        "- 完整观察值、分组统计、分组差值与运行元数据均在同目录CSV/JSON文件中。",
        "",
    ])
    return "\n".join(lines)


def run_research(
    amv_path: Path,
    etf_path: Path,
    output_dir: Path,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run train, OOS, and all-sample 0AMV momentum decile research."""
    horizons = tuple(int(value) for value in horizons)
    factors = build_momentum_factor(load_amv_csv(amv_path))
    observations = attach_etf_forward_returns(factors, normalize_etf_history(pd.read_csv(etf_path)), horizons)
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[pd.DataFrame] = []
    for stage, (start, end) in scoped_ranges(SAMPLES, include_all=True).items():
        rows = observations.copy()
        if start is not None:
            rows = rows.loc[rows["date"] >= pd.Timestamp(start)]
        if end is not None:
            rows = rows.loc[rows["date"] <= pd.Timestamp(end)]
        grouped = assign_momentum_deciles(rows.reset_index(drop=True))
        grouped.to_csv(output_dir / f"observations_{stage}.csv", index=False, encoding="utf-8-sig")
        summaries.append(summarize_deciles(grouped, stage, horizons))
    summary = pd.concat(summaries, ignore_index=True)
    effects = summarize_effects(summary, horizons)
    summary.to_csv(output_dir / "momentum_decile_summary.csv", index=False, encoding="utf-8-sig")
    effects.to_csv(output_dir / "momentum_effect_summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(format_report(summary, effects, horizons), encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps({
        "amv_path": str(amv_path),
        "etf_path": str(etf_path),
        "factor": "amv_close(t) / amv_close(t-3) - 1",
        "date_universe": "intersection of 0AMV and 510300 ETF dates",
        "deciles": "within-stage equal-count deciles; Q1 lowest, Q10 highest",
        "entry": "next ETF session open",
        "horizons": list(horizons),
        "samples": SAMPLES,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary, effects


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf", type=Path, default=Path("data/backtest_data/510300.SH.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/factor_research_runs/amv_3d_momentum_deciles"))
    args = parser.parse_args()
    summary, effects = run_research(args.amv, args.etf, args.output)
    print(summary.to_string(index=False))
    print("\nQ10-Q1 / monotonicity")
    print(effects.to_string(index=False))


if __name__ == "__main__":
    main()
