"""分析每日预筛选数量与交易胜率的关系。

数据来源: data/backtest_runs/final_2024/ + final_2025/
- daily_ratings.csv: 每日预筛选通过的股票评分记录
- trades.csv: 交易明细

输出: 按每日预筛选数量分档后的交易胜率统计表
"""
from __future__ import annotations

import csv
import logging
from collections import defaultdict
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUNS = ["final_2024", "final_2025", "2025_timing"]

# 分档边界 (prefilter count bins)
BINS = [0, 50, 100, 150, 200, 300, 400, 500, 1000]


def load_daily_prefilter_counts(run_dir: Path) -> dict[str, int]:
    """从 daily_ratings.csv 按日期统计预筛选股票数。"""
    ratings_path = run_dir / "daily_ratings.csv"
    if not ratings_path.exists():
        logger.warning(f"找不到 {ratings_path}")
        return {}

    df = pd.read_csv(ratings_path, usecols=["date"])
    counts = df.groupby("date").size()
    return counts.to_dict()


def load_trades(run_dir: Path) -> pd.DataFrame:
    """读取交易记录，提取 buy_date 和 pnl_pct。"""
    trades_path = run_dir / "trades.csv"
    if not trades_path.exists():
        logger.warning(f"找不到 {trades_path}")
        return pd.DataFrame()

    df = pd.read_csv(trades_path, usecols=["buy_date", "pnl_pct"])
    df["pnl_pct"] = pd.to_numeric(df["pnl_pct"], errors="coerce")
    return df.dropna(subset=["pnl_pct"])


def bin_label(low: int, high: int) -> str:
    if high == float("inf"):
        return f">={low}"
    return f"{low}-{high - 1}"


def main():
    all_trades = []
    run_info = {}

    for run_name in RUNS:
        run_dir = PROJECT_ROOT / "data" / "backtest_runs" / run_name
        counts = load_daily_prefilter_counts(run_dir)
        trades = load_trades(run_dir)

        if trades.empty or not counts:
            logger.warning(f"{run_name}: 数据缺失，跳过")
            continue

        # 关联每日预筛选数量
        trades["pref_count"] = trades["buy_date"].map(counts)
        trades["run"] = run_name
        trades = trades.dropna(subset=["pref_count"])

        all_trades.append(trades)
        run_info[run_name] = {
            "trading_days": len(counts),
            "trades_total": len(trades),
            "avg_pref": sum(counts.values()) / len(counts) if counts else 0,
        }

    if not all_trades:
        logger.error("无有效数据")
        return

    df = pd.concat(all_trades, ignore_index=True)

    # ── 分档统计 ──
    df["bin"] = pd.cut(
        df["pref_count"],
        bins=BINS + [float("inf")],
        right=False,
        labels=[bin_label(BINS[i], BINS[i + 1]) for i in range(len(BINS) - 1)]
        + [bin_label(BINS[-1], float("inf"))],
    )

    results = []
    for label in df["bin"].cat.categories:
        subset = df[df["bin"] == label]
        if len(subset) < 3:
            continue  # 样本太少跳过
        wins = (subset["pnl_pct"] > 0).sum()
        losses = (subset["pnl_pct"] <= 0).sum()
        total = len(subset)
        win_rate = wins / total * 100
        avg_pnl = subset["pnl_pct"].mean()
        avg_win = subset[subset["pnl_pct"] > 0]["pnl_pct"].mean()
        avg_loss = subset[subset["pnl_pct"] <= 0]["pnl_pct"].mean()
        results.append({
            "pref_count_range": label,
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(win_rate, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
        })

    # ── 打印 ──
    print(f"\n{'=' * 95}")
    print("  每日预筛选数量 vs 交易胜率  (2024-2025)")
    print(f"{'=' * 95}")

    for name, info in run_info.items():
        print(f"  {name}: {info['trading_days']} 交易日, "
              f"{info['trades_total']} 笔交易, "
              f"日均预筛选 {info['avg_pref']:.0f} 只")

    print(f"\n  总交易笔数: {len(df)}")
    total_wins = (df["pnl_pct"] > 0).sum()
    print(f"  总胜率: {total_wins / len(df) * 100:.1f}%")
    print(f"  预筛选数量范围: {df['pref_count'].min():.0f} - {df['pref_count'].max():.0f}")
    print(f"  预筛选中位数: {df['pref_count'].median():.0f}")
    print(f"\n{'─' * 95}")
    print(f"  {'预筛选范围':>12}  {'笔数':>5}  {'胜':>4}  {'负':>4}  {'胜率':>7}  {'均pnl%':>8}  {'均盈%':>7}  {'均亏%':>7}")
    print(f"  {'─' * 65}")
    for r in results:
        bar = "█" * max(1, int(r["win_rate_pct"] / 5))
        print(
            f"  {r['pref_count_range']:>12}  "
            f"{r['total_trades']:>5}  "
            f"{r['wins']:>4}  "
            f"{r['losses']:>4}  "
            f"{r['win_rate_pct']:>6.1f}%  "
            f"{r['avg_pnl_pct']:>+8.2f}  "
            f"{r['avg_win_pct']:>+7.2f}  "
            f"{r['avg_loss_pct']:>+7.2f}  "
            f"  {bar}"
        )
    print(f"{'─' * 95}")

    # ── 写 CSV ──
    out_path = PROJECT_ROOT / "data" / "analysis_prefilter_winrate.csv"
    pd.DataFrame(results).to_csv(out_path, index=False, encoding="utf-8")
    print(f"\n已保存到: {out_path}")

    # ── 补充：按年份分别统计 ──
    print(f"\n{'=' * 70}")
    print("  分年份统计")
    print(f"{'=' * 70}")
    for run_name in RUNS:
        subset = df[df["run"] == run_name]
        if subset.empty:
            continue
        wins = (subset["pnl_pct"] > 0).sum()
        total = len(subset)
        print(f"  {run_name}: {total} 笔, 胜率 {wins / total * 100:.1f}%, "
              f"均pnl {subset['pnl_pct'].mean():+.2f}%, "
              f"日中位pref {subset['pref_count'].median():.0f}")

    # ── 线性相关性 ──
    corr = df["pref_count"].corr(df["pnl_pct"])
    print(f"\n  pref_count vs pnl_pct 线性相关系数: {corr:.4f} "
          f"({'正相关' if corr > 0.05 else '负相关' if corr < -0.05 else '无明显线性关系'})")


if __name__ == "__main__":
    main()
