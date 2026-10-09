"""Study 3-day momentum for rolling-P85 sells while AMV MA10 > MA30.

The candidate definition deliberately removes the MA3 flat/down confirmation.
For each P85 candidate universe, 3-day momentum is split into five groups and
the next-session-open 510300 forward return is measured.
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


DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
DEFAULT_WINDOW = 750
SAMPLES = {"train": ("2015-01-01", "2023-12-31"), "oos": ("2024-01-01", "2025-12-31")}
UNIVERSES = {
    "sell_1_gap10_p85": ("sell_1_candidate", "gap10 > rolling P85(gap10)"),
    "sell_2_gap20_p85": ("sell_2_candidate", "gap20 > rolling P85(gap20)"),
    "either_gap_p85": ("either_candidate", "sell_1 OR sell_2"),
    "both_gap_p85": ("both_candidate", "sell_1 AND sell_2"),
}


def build_sell_candidates(amv: pd.DataFrame, window: int = DEFAULT_WINDOW, min_periods: int | None = None) -> pd.DataFrame:
    """Compute look-ahead-safe P85 candidates without MA3 confirmation."""
    missing = {"date", "close"}.difference(amv.columns)
    if missing:
        raise ValueError(f"0AMV 数据缺少列: {', '.join(sorted(missing))}")
    minimum = window if min_periods is None else min_periods
    if not 0 < minimum <= window:
        raise ValueError("min_periods 必须在 1 到 window 之间")
    result = amv.loc[:, ["date", "close"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    result["close"] = pd.to_numeric(result["close"], errors="raise")
    result = result.sort_values("date").reset_index(drop=True)
    if result["date"].duplicated().any() or (result["close"] <= 0).any():
        raise ValueError("0AMV 数据存在重复日期或非正收盘价")
    result["ma10"] = result["close"].rolling(10, min_periods=10).mean()
    result["ma20"] = result["close"].rolling(20, min_periods=20).mean()
    result["ma30"] = result["close"].rolling(30, min_periods=30).mean()
    result["gap10"] = result["close"] / result["ma10"] - 1.0
    result["gap20"] = result["close"] / result["ma20"] - 1.0
    result["momentum_3"] = result["close"].pct_change(3)
    result["gap10_p85"] = result["gap10"].rolling(window, min_periods=minimum).quantile(.85).shift(1)
    result["gap20_p85"] = result["gap20"].rolling(window, min_periods=minimum).quantile(.85).shift(1)
    result["ma10_above_ma30"] = result["ma10"] > result["ma30"]
    result["sell_1_candidate"] = result["ma10_above_ma30"] & (result["gap10"] > result["gap10_p85"])
    result["sell_2_candidate"] = result["ma10_above_ma30"] & (result["gap20"] > result["gap20_p85"])
    result["either_candidate"] = result["sell_1_candidate"] | result["sell_2_candidate"]
    result["both_candidate"] = result["sell_1_candidate"] & result["sell_2_candidate"]
    return result


def assign_momentum_quintiles(frame: pd.DataFrame) -> pd.DataFrame:
    """Label lowest to highest 3-day momentum as Q1 to Q5."""
    if "momentum_3" not in frame:
        raise ValueError("样本缺少 momentum_3 列")
    result = frame.copy()
    result["momentum_quintile"] = pd.Series(pd.NA, index=result.index, dtype="string")
    valid = result["momentum_3"].notna()
    if valid.sum() >= 5:
        ranks = result.loc[valid, "momentum_3"].rank(method="first")
        result.loc[valid, "momentum_quintile"] = pd.qcut(ranks, 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"]).astype("string").to_numpy()
    return result


def attach_etf_forward_returns(candidates: pd.DataFrame, etf: pd.DataFrame, horizons: Iterable[int] = DEFAULT_HORIZONS) -> pd.DataFrame:
    """Attach next ETF session open to Nth-session-close return."""
    prices = etf.loc[:, ["date", "open", "close"]].copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="raise").dt.normalize()
    prices = prices.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    result = candidates.copy()
    indices = prices["date"].to_numpy(dtype="datetime64[ns]").searchsorted(result["date"].to_numpy(dtype="datetime64[ns]"), side="right")
    available = indices < len(prices)
    result = result.loc[available].copy().reset_index(drop=True)
    indices = indices[available]
    result["entry_date"] = prices.iloc[indices]["date"].to_numpy()
    result["entry_open"] = prices.iloc[indices]["open"].to_numpy()
    for horizon in (int(value) for value in horizons):
        exit_indices = indices + horizon - 1
        values = pd.Series(float("nan"), index=result.index)
        valid = exit_indices < len(prices)
        values.loc[valid] = (prices.iloc[exit_indices[valid]]["close"].to_numpy() / result.loc[valid, "entry_open"].to_numpy() - 1) * 100
        result[f"forward_return_{horizon}_pct"] = values
    return result


def summarize_groups(observations: pd.DataFrame, universe: str, stage: str, horizons: Iterable[int]) -> pd.DataFrame:
    rows = []
    for quintile in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        group = observations.loc[observations["momentum_quintile"] == quintile]
        row = {"universe": universe, "stage": stage, "momentum_quintile": quintile, "sample_count": len(group),
               "momentum_3_min_pct": group["momentum_3"].min() * 100, "momentum_3_mean_pct": group["momentum_3"].mean() * 100,
               "momentum_3_median_pct": group["momentum_3"].median() * 100, "momentum_3_max_pct": group["momentum_3"].max() * 100}
        for horizon in horizons:
            values = group[f"forward_return_{int(horizon)}_pct"].dropna()
            row[f"return_{int(horizon)}d_mean_pct"] = values.mean()
            row[f"return_{int(horizon)}d_median_pct"] = values.median()
            row[f"return_{int(horizon)}d_win_rate_pct"] = (values > 0).mean() * 100
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_momentum_effect(summary: pd.DataFrame, horizons: Iterable[int]) -> pd.DataFrame:
    """Measure whether lower momentum is followed by lower ETF returns."""
    rows = []
    order = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    for (universe, stage), group in summary.groupby(["universe", "stage"], sort=False):
        indexed = group.set_index("momentum_quintile").reindex(order)
        for horizon in horizons:
            means = indexed[f"return_{int(horizon)}d_mean_pct"]
            q5_minus_q1 = means.loc["Q5"] - means.loc["Q1"]
            rows.append({
                "universe": universe,
                "stage": stage,
                "horizon": int(horizon),
                "q5_minus_q1_pct": q5_minus_q1,
                "group_spearman": pd.Series(range(1, 6), dtype="float64").corr(means.reset_index(drop=True).rank()),
                "strictly_increasing": bool(means.is_monotonic_increasing),
                "supports_low_momentum_sell": bool(q5_minus_q1 > 0),
            })
    return pd.DataFrame(rows)


def format_report(summary: pd.DataFrame, effects: pd.DataFrame, horizons: Iterable[int]) -> str:
    lines = ["# MA10>MA30 时的 0AMV P85 早期卖点：3日动量五分组研究", "", "样本先限定 `0AMV MA10 > MA30`，取消 `MA3(t)-MA3(t-1)<=0` 确认，再保留滚动 P85 高乖离。", "收益口径：信号日后下一 ETF 交易日开盘至第 N 个交易日收盘的 510300 收益；对卖点而言，后续收益越低越有利。", ""]
    for universe, (_, description) in UNIVERSES.items():
        lines.extend([f"## {universe}：{description}", ""])
        for stage in ("train", "oos", "all"):
            rows = summary.loc[(summary["universe"] == universe) & (summary["stage"] == stage)]
            if rows.empty:
                continue
            lines.extend([f"### {stage.upper()}", "", "| 动量组 | 样本 | 3日动量均值 | " + " | ".join(f"{h}日ETF均值/胜率" for h in horizons) + " |", "|---|---:|---:|" + "---:|" * len(tuple(horizons))])
            for row in rows.to_dict("records"):
                cells = [row["momentum_quintile"], str(row["sample_count"]), f'{row["momentum_3_mean_pct"]:+.2f}%']
                cells += [f'{row[f"return_{h}d_mean_pct"]:+.2f}% / {row[f"return_{h}d_win_rate_pct"]:.1f}%' for h in horizons]
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
        lines.extend(["### Q5-Q1 与单调性", "", "| 阶段 | 周期 | Q5-Q1 | 组序Spearman | 严格递增 | 支持低动量更适合卖出 |", "|---|---:|---:|---:|---:|---:|"])
        for row in effects.loc[effects["universe"] == universe].to_dict("records"):
            lines.append(
                f'| {row["stage"].upper()} | {row["horizon"]}日 | {row["q5_minus_q1_pct"]:+.2f}% | '
                f'{row["group_spearman"]:+.2f} | {"是" if row["strictly_increasing"] else "否"} | '
                f'{"是" if row["supports_low_momentum_sell"] else "否"} |'
            )
        lines.append("")
    lines.extend(["## 口径说明", "", "- 只研究 `0AMV MA10 > MA30` 的上升趋势状态。", "- P85 阈值由此前 750 个交易日计算并向后移动一天；不使用 MA3 转平确认。", "- Q1 为最低三日动量，Q5 为最高三日动量；TRAIN、OOS、全样本内部独立等频分组。", "- 这是重叠事件的条件收益研究，不等价于完整持仓净值回测。完整样本与分位边界见同目录 CSV。", ""])
    return "\n".join(lines)


def run_research(amv_path: Path, etf_path: Path, output_dir: Path, horizons: Iterable[int] = DEFAULT_HORIZONS) -> pd.DataFrame:
    horizons = tuple(int(value) for value in horizons)
    candidates = attach_etf_forward_returns(build_sell_candidates(load_amv_csv(amv_path)), normalize_etf_history(pd.read_csv(etf_path)), horizons)
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    for universe, (selector, _) in UNIVERSES.items():
        for stage, dates in scoped_ranges(SAMPLES, include_all=True).items():
            rows = candidates.loc[candidates[selector]].copy()
            if dates[0] is not None:
                rows = rows.loc[rows["date"] >= pd.Timestamp(dates[0])]
            if dates[1] is not None:
                rows = rows.loc[rows["date"] <= pd.Timestamp(dates[1])]
            grouped = assign_momentum_quintiles(rows.reset_index(drop=True))
            grouped.to_csv(output_dir / f"observations_{universe}_{stage}.csv", index=False, encoding="utf-8-sig")
            summaries.append(summarize_groups(grouped, universe, stage, horizons))
    summary = pd.concat(summaries, ignore_index=True)
    effects = summarize_momentum_effect(summary, horizons)
    summary.to_csv(output_dir / "momentum_quintile_summary.csv", index=False, encoding="utf-8-sig")
    effects.to_csv(output_dir / "momentum_effect_summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(format_report(summary, effects, horizons), encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps({"condition": "amv_ma10 > amv_ma30", "window": DEFAULT_WINDOW, "threshold": "prior rolling P85", "ma3_confirmation": False, "horizons": horizons, "entry": "next ETF session open", "samples": SAMPLES}, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf", type=Path, default=Path("data/backtest_data/510300.SH.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/factor_research_runs/amv_sell_p85_momentum_quintiles"))
    args = parser.parse_args()
    print(run_research(args.amv, args.etf, args.output).to_string(index=False))


if __name__ == "__main__":
    main()
