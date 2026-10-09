"""Phase 0: parquet 数据摸底。

一次性脚本，用于回测正式开发前的数据质量验证：
- 复权状态（已确认前复权）
- 涨跌停标记 / 阈值
- 停牌/退市处理
- 日均活跃股票数量
- 次日开盘价是否在涨跌停范围内
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


DATA_DIR = Path("data/backtest_data/5m_price")


def load_day(date_str: str, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    year = date_str[:4]
    path = data_dir / year / f"{date_str}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pq.read_table(path).to_pandas()


def aggregate_to_daily(df_5min: pd.DataFrame) -> pd.DataFrame:
    """5min → 日线（每个股票一行）。"""
    if df_5min.empty:
        return pd.DataFrame()
    g = df_5min.groupby("code")
    daily = pd.DataFrame({
        "code": g["code"].first(),
        "date": g["date"].first(),
        "open": g["open"].first(),
        "close": g["close"].last(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "vol": g["vol"].sum(),
        "amount": g["amount"].sum(),
        "pre_close": g["pre_close"].apply(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan),
        "n_bars": g.size(),
    }).reset_index(drop=True)
    daily["pct_chg"] = (daily["close"] - daily["pre_close"]) / daily["pre_close"] * 100
    return daily


def audit_year(year: int, sample_days: int = 20):
    """对一年的数据采样审计。"""
    print(f"\n{'='*70}")
    print(f"  Year {year} audit (sample {sample_days} days)")
    print(f"{'='*70}")
    files = sorted(glob.glob(str(DATA_DIR / str(year) / "*.parquet")))
    print(f"Total trading days: {len(files)}")

    if not files:
        return

    # 等距采样
    step = max(1, len(files) // sample_days)
    samples = files[::step][:sample_days]

    stats = []
    for f in samples:
        date_str = Path(f).stem
        df_5min = pq.read_table(f).to_pandas()
        daily = aggregate_to_daily(df_5min)
        if daily.empty:
            continue

        n_stocks = len(daily)
        n_limit_up = int((daily["pct_chg"] >= 9.8).sum())
        n_limit_down = int((daily["pct_chg"] <= -9.8).sum())
        n_st_limit_up = int((daily["pct_chg"] >= 4.8).sum() - n_limit_up)  # ST 5%涨停
        n_5min_bars = df_5min.groupby("code").size().mode().iloc[0]  # 多数股票的bar数

        stats.append({
            "date": date_str,
            "stocks": n_stocks,
            "limit_up": n_limit_up,
            "limit_down": n_limit_down,
            "5min_bars": int(n_5min_bars),
            "max_pct": daily["pct_chg"].max(),
            "min_pct": daily["pct_chg"].min(),
        })

    sdf = pd.DataFrame(stats)
    print(f"\n股票数量统计:")
    print(f"  最小: {sdf['stocks'].min()}, 最大: {sdf['stocks'].max()}, 均值: {sdf['stocks'].mean():.0f}")
    print(f"\n涨停股(>=9.8%):")
    print(f"  最小: {sdf['limit_up'].min()}, 最大: {sdf['limit_up'].max()}, 均值: {sdf['limit_up'].mean():.1f}")
    print(f"\n跌停股(<=-9.8%):")
    print(f"  最小: {sdf['limit_down'].min()}, 最大: {sdf['limit_down'].max()}, 均值: {sdf['limit_down'].mean():.1f}")
    print(f"\n5min bar 数（应为48）:")
    print(f"  值分布: {sorted(sdf['5min_bars'].unique())}")
    print(f"\n单日最大涨跌幅范围:")
    print(f"  max_pct 最大: {sdf['max_pct'].max():.2f}%")
    print(f"  min_pct 最小: {sdf['min_pct'].min():.2f}%")


def audit_consecutive_days(date1: str, date2: str):
    """验证两个连续交易日的复权连续性。"""
    print(f"\n{'='*70}")
    print(f"  复权连续性验证: {date1} -> {date2}")
    print(f"{'='*70}")
    df1 = aggregate_to_daily(load_day(date1))
    df2 = aggregate_to_daily(load_day(date2))
    if df1.empty or df2.empty:
        print("缺少数据")
        return
    merged = df1[["code", "close"]].merge(
        df2[["code", "pre_close"]], on="code", suffixes=("_d1", "_d2")
    )
    merged["diff"] = (merged["close"] - merged["pre_close"]).abs()
    n_match = (merged["diff"] < 0.01).sum()
    n_total = len(merged)
    print(f"复权对齐: {n_match}/{n_total} ({n_match/n_total*100:.1f}%) 股票的 D1.close == D2.pre_close")
    if n_match < n_total:
        mismatch = merged[merged["diff"] >= 0.01].head(5)
        print(f"前5个不匹配样本（可能是除权除息）:")
        print(mismatch.to_string(index=False))


def audit_st_distribution(date_str: str):
    """检查 ST 股票分布（pct_chg 约 ±5% 限制）。"""
    print(f"\n{'='*70}")
    print(f"  ST 股票分布: {date_str}")
    print(f"{'='*70}")
    daily = aggregate_to_daily(load_day(date_str))
    if daily.empty:
        print("缺少数据")
        return
    # 推断 ST：股价较低 + 涨跌幅触及±5%但不到±10%
    suspect_st = daily[(daily["pct_chg"].abs() >= 4.8) & (daily["pct_chg"].abs() < 5.2)]
    print(f"涨跌幅在±[4.8%, 5.2%]区间的股票数: {len(suspect_st)}")
    if len(suspect_st) > 0:
        print(suspect_st[["code", "close", "pct_chg"]].head(10).to_string(index=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=[2015, 2020, 2024])
    parser.add_argument("--sample-days", type=int, default=10)
    args = parser.parse_args()

    for year in args.years:
        audit_year(year, args.sample_days)

    audit_consecutive_days("20240102", "20240103")
    audit_consecutive_days("20200102", "20200103")

    audit_st_distribution("20240103")


if __name__ == "__main__":
    main()
