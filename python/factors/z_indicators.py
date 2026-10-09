"""指标计算层。

直接复用 python/scoring/brick_indicator.py 中已实现的：
- compute_zx_lines(df, ...) → (zxdq, zxdkx)  知行黄白线
- compute_kdj(df, n=9) → df + (K, D, J)      KDJ

提供两种使用方式：
1. compute_all_indicators(stock_df) — 单股票计算（用于小数据集测试）
2. precompute_all_indicators_parallel(daily_df, n_workers) — 全市场预计算
   一次性对全市场所有股票的全历史算好指标，回测主循环直接查表
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from multiprocessing import Pool

import numpy as np
import pandas as pd

from python.scoring.brick_indicator import compute_kdj, compute_zx_lines

logger = logging.getLogger(__name__)


def compute_dynamic_weekly_kdj(
    daily: pd.DataFrame,
    *,
    splits: dict[pd.Timestamp, float] | None = None,
    cash_dividends: dict[pd.Timestamp, float] | None = None,
) -> pd.DataFrame:
    """Compute KDJ(9,3,3) at each close, including the visible part of that week.

    Each day's provisional weekly candle starts from the preceding completed
    week's K/D. Split/dividend factors apply only from their effective date forward;
    the returned readings never depend on later prices or corporate actions.
    """
    required = {"date", "high", "low", "close"}
    if not required.issubset(daily.columns):
        raise ValueError(f"周线 KDJ 数据缺少列: {sorted(required - set(daily.columns))}")
    frame = daily.loc[:, ["date", "high", "low", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame = frame.sort_values("date").reset_index(drop=True)
    if frame["date"].isna().any() or frame["date"].duplicated().any():
        raise ValueError("周线 KDJ 数据存在缺失或重复日期")
    prices = ["high", "low", "close"]
    frame[prices] = frame[prices].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(frame[prices].to_numpy()).all():
        raise ValueError("周线 KDJ 数据存在非有限价格")
    raw_close = frame.set_index("date")["close"].copy()
    for date, amount in sorted((cash_dividends or {}).items()):
        date = pd.Timestamp(date).normalize()
        if pd.isna(date):
            raise ValueError("分红日期不得缺失")
        if not np.isfinite(amount) or amount <= 0:
            raise ValueError("每股分红必须为有限正数")
        if frame.empty or date <= frame.iloc[0]["date"] or date > frame.iloc[-1]["date"]:
            continue
        previous_close = float(raw_close.loc[raw_close.index < date].iloc[-1])
        if amount >= previous_close:
            raise ValueError("每股分红必须小于除息前收盘价")
        # Forward-only continuity: future dividends cannot rewrite earlier J.
        frame.loc[frame["date"] >= date, prices] *= previous_close / (previous_close - amount)
    for date, ratio in sorted((splits or {}).items()):
        if not np.isfinite(ratio) or ratio <= 0:
            raise ValueError("拆分倍数必须为有限正数")
        frame.loc[frame["date"] >= pd.Timestamp(date).normalize(), prices] *= ratio

    history = frame.set_index("date")
    rows = []
    for date in history.index:
        weekly = history.loc[:date].resample("W-FRI").agg(
            {"high": "max", "low": "min", "close": "last"}
        ).dropna()
        reading = compute_kdj(weekly, n=9).iloc[-1] if len(weekly) >= 9 else None
        rows.append({"date": date, **{column: float(reading[column]) if reading is not None else np.nan
                                     for column in ("K", "D", "J")}})
    return pd.DataFrame(rows, columns=["date", "K", "D", "J"])


def compute_all_indicators(stock_df: pd.DataFrame) -> pd.DataFrame:
    """对单只股票的历史日线计算 KDJ + 黄白线。"""
    if len(stock_df) < 15:
        return stock_df.assign(K=np.nan, D=np.nan, J=np.nan, zxdq=np.nan, zxdkx=np.nan)

    df = compute_kdj(stock_df, n=9)
    zxdq, zxdkx = compute_zx_lines(df)
    df["zxdq"] = zxdq.values
    df["zxdkx"] = zxdkx.values
    return df


def _compute_for_one_stock(args: tuple[str, pd.DataFrame]) -> tuple[str, np.ndarray]:
    """worker：算一只股票的指标，返回 (code, ndarray[N, 5])。

    ndarray 列顺序: [K, D, J, zxdq, zxdkx]
    用 ndarray 而不是 DataFrame 跨进程传输，pickle 体积小 3-4 倍。
    """
    code, df = args
    n = len(df)
    if n < 15:
        return code, np.full((n, 5), np.nan, dtype=np.float64)

    df_kdj = compute_kdj(df, n=9)
    zxdq, zxdkx = compute_zx_lines(df_kdj)

    arr = np.empty((n, 5), dtype=np.float64)
    arr[:, 0] = df_kdj["K"].values
    arr[:, 1] = df_kdj["D"].values
    arr[:, 2] = df_kdj["J"].values
    arr[:, 3] = zxdq.values
    arr[:, 4] = zxdkx.values
    return code, arr


def precompute_all_indicators_parallel(
    daily_df: pd.DataFrame, n_workers: int = 1
) -> pd.DataFrame:
    """对 daily_df 的全部 (code, 全历史) 一次性算指标并回填。

    Args:
        daily_df: DataLoader 加载好的全市场日线长表
        n_workers: 进程数，1=单进程

    Returns:
        原 daily_df + K/D/J/zxdq/zxdkx 列（按 (code, date) 升序）
    """
    logger.info(f"Precomputing indicators for {daily_df['code'].nunique()} stocks "
                f"({len(daily_df):,} rows) with {n_workers} workers...")

    # 确保按 (code, date) 升序
    df = daily_df.sort_values(["code", "date"]).reset_index(drop=True)

    # 按 code 切片成任务
    tasks = [(code, g) for code, g in df.groupby("code", sort=False)]

    # 输出列预分配
    out = np.full((len(df), 5), np.nan, dtype=np.float64)

    # 为每个 code 找到它在 df 中的行索引区间（已按 code 排序，可直接 cumsum）
    code_sizes = df.groupby("code", sort=False).size()
    starts = code_sizes.cumsum().shift(1).fillna(0).astype(int)
    code_to_start = dict(zip(code_sizes.index, starts.values))

    if n_workers <= 1:
        for code, sub in tasks:
            _, arr = _compute_for_one_stock((code, sub))
            s = code_to_start[code]
            out[s:s + len(arr)] = arr
    else:
        with Pool(n_workers) as pool:
            for code, arr in pool.imap_unordered(_compute_for_one_stock, tasks, chunksize=64):
                s = code_to_start[code]
                out[s:s + len(arr)] = arr

    df["K"] = out[:, 0]
    df["D"] = out[:, 1]
    df["J"] = out[:, 2]
    df["zxdq"] = out[:, 3]
    df["zxdkx"] = out[:, 4]
    logger.info("Precompute done (daily).")

    # 追加周线/月线指标
    df = _add_weekly_monthly_indicators(df)
    logger.info("Precompute done (weekly/monthly).")
    return df


def _add_weekly_monthly_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """在日线 DataFrame 上追加周线 KD+J 和知行黄白线 + 月线 MA20。

    优化：先构建周线 DataFrame → 计算指标 → merge_asof 回填日线。
    避免逐 stocks reindex 的 O(n²) 开销。
    """
    df = df.copy()
    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.sort_values(["code", "date_dt"])

    weekly_rows = []
    monthly_rows = []

    for code, sub in df.groupby("code", sort=False):
        sub = sub.set_index("date_dt")
        if len(sub) < 10:
            continue

        # 周线聚合
        w = sub.resample("W").agg({
            "open": "first", "close": "last",
            "high": "max", "low": "min",
        }).dropna()

        if len(w) >= 9:
            w_df = compute_kdj(w)
            w["w_J"] = w_df["J"]
            # 周线 zx 线从日线已有值聚合（zxdkx的MA周期太长不适合周线）
            w["w_zxdq"] = sub["zxdq"].resample("W").last().dropna()
            w["w_zxdkx"] = sub["zxdkx"].resample("W").last().dropna()
            w["code"] = code
            weekly_rows.append(w[["code", "w_J", "w_zxdq", "w_zxdkx"]].reset_index())

        # 月线 MA20
        m = sub.resample("ME").agg({"close": "last"}).dropna()
        if len(m) >= 1:
            m["m_MA20"] = m["close"].rolling(20, min_periods=1).mean()
            m["code"] = code
            monthly_rows.append(m[["code", "m_MA20"]].reset_index())

    # 用 merge_asof 高效回填到日线
    if weekly_rows:
        weekly_all = pd.concat(weekly_rows, ignore_index=True)
        weekly_all = weekly_all.rename(columns={"date_dt": "date_dt"})
        # merge_asof: 对每行日线，找 <= 它的最近周线数据
        df = pd.merge_asof(
            df.sort_values("date_dt"),
            weekly_all.sort_values("date_dt"),
            by="code", on="date_dt", direction="backward",
        )

    if monthly_rows:
        monthly_all = pd.concat(monthly_rows, ignore_index=True)
        monthly_all = monthly_all.rename(columns={"date_dt": "date_dt"})
        df = pd.merge_asof(
            df.sort_values("date_dt"),
            monthly_all.sort_values("date_dt"),
            by="code", on="date_dt", direction="backward",
        )

    df["date"] = df["date_dt"].dt.strftime("%Y%m%d")
    df = df.drop(columns=["date_dt"])
    return df


def prefilter_by_kdj_zx_vectorized(
    daily_df_with_ind: pd.DataFrame,
    as_of_date: str,
    j_threshold: float = 13.0,
) -> list[str]:
    """向量化版本的盘前粗筛 — 直接从含指标的长表切片。

    防未来函数：用 < as_of_date 的最后一行（即 as_of_date 前一交易日的收盘数据）。
    条件：
    1. J < j_threshold
    2. close > zxdkx
    3. zxdq > zxdkx
    """
    df = daily_df_with_ind
    # 每只股票在 as_of_date 之前的最后一行
    mask = df["date"] < as_of_date
    if not mask.any():
        return []
    last_rows = df.loc[mask].groupby("code", sort=False).tail(1)
    if last_rows.empty:
        return []
    cond = (
        last_rows["J"].notna()
        & last_rows["zxdq"].notna()
        & last_rows["zxdkx"].notna()
        & (last_rows["J"] < j_threshold)
        & (last_rows["close"] > last_rows["zxdkx"])
        & (last_rows["zxdq"] > last_rows["zxdkx"])
    )
    return last_rows.loc[cond, "code"].tolist()


def build_prefilter_cache(
    daily_df_with_ind: pd.DataFrame,
    trading_days: Sequence[str],
    j_threshold: float = 13.0,
) -> dict[str, list[str]]:
    """Cache the point-in-time KDJ/ZX prefilter for each trading date.

    The cache entry for ``T`` is assembled before applying rows from ``T``;
    therefore it has the same "last available row before T" semantics as
    :func:`prefilter_by_kdj_zx_vectorized`, including stocks suspended on T-1.
    """
    required = {"date", "code", "J", "zxdq", "zxdkx", "close"}
    missing = required.difference(daily_df_with_ind.columns)
    if missing:
        raise ValueError(f"预筛选数据缺少列: {', '.join(sorted(missing))}")

    groups = daily_df_with_ind.groupby("date", sort=False).indices
    active_codes: set[str] = set()
    cache: dict[str, list[str]] = {}
    for date in trading_days:
        cache[date] = sorted(active_codes)
        indexes = groups.get(date)
        if indexes is None:
            continue
        day = daily_df_with_ind.iloc[indexes]
        active_codes.difference_update(day["code"])
        passed = day.loc[
            day["J"].notna()
            & day["zxdq"].notna()
            & day["zxdkx"].notna()
            & (day["J"] < j_threshold)
            & (day["close"] > day["zxdkx"])
            & (day["zxdq"] > day["zxdkx"]),
            "code",
        ]
        active_codes.update(passed)
    return cache


# ── 旧 API 保留向后兼容 ──

def compute_universe_indicators(
    universe_history: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """旧 API：对全市场每只股票批量计算指标（已被预计算方案取代）。"""
    out = {}
    for code, df in universe_history.items():
        out[code] = compute_all_indicators(df)
    return out


def prefilter_by_kdj_zx(
    universe_indicators: dict[str, pd.DataFrame],
    j_threshold: float = 13.0,
) -> list[str]:
    """旧 API：dict-style 粗筛。"""
    passed = []
    for code, df in universe_indicators.items():
        if df.empty:
            continue
        last = df.iloc[-1]
        if pd.isna(last["J"]) or pd.isna(last["zxdq"]) or pd.isna(last["zxdkx"]):
            continue
        if (
            last["J"] < j_threshold
            and last["close"] > last["zxdkx"]
            and last["zxdq"] > last["zxdkx"]
        ):
            passed.append(code)
    return passed
