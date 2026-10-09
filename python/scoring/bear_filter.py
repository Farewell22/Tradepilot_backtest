"""熊市选股器：周线KDJ + 知行白黄线。"""
from __future__ import annotations

import pandas as pd


def bear_prefilter(
    daily_df: pd.DataFrame,
    as_of_date: str,
    config: dict | None = None,
) -> list[str]:
    """熊市选股初筛。降级策略：无成交量限制。

    第一级：周线白>黄 + 周线J<13
    第二级（降级）：仅周线白>黄
    """
    cfg = (config or {}).get("bear_filter", {})
    j_max = cfg.get("weekly_kdj_j_max", 13)

    df = daily_df[daily_df["date"] <= as_of_date].copy()
    if df.empty:
        return []

    latest = df.sort_values("date").groupby("code").tail(1).copy()
    if latest.empty:
        return []

    # 市值门槛：当日成交额 >= 3000万（流通市值约60亿的代理指标）
    if "amount" in latest.columns:
        mask = latest["amount"] >= 30_000_000
    else:
        mask = pd.Series(True, index=latest.index)

    zx_cols = ("w_zxdq" in latest.columns and "w_zxdkx" in latest.columns)
    j_col = "w_J" in latest.columns

    if zx_cols:
        mask &= latest["w_zxdq"] > latest["w_zxdkx"]
    elif "zxdq" in latest.columns:
        mask &= latest["zxdq"] > latest["zxdkx"]

    # 周线和日线 J 都必须 < 阈值
    if j_col and "J" in latest.columns:
        mask &= (latest["w_J"] < j_max) & (latest["J"] < j_max)
    elif j_col:
        mask &= latest["w_J"] < j_max
    elif "J" in latest.columns:
        mask &= latest["J"] < j_max

    return latest[mask]["code"].unique().tolist()
