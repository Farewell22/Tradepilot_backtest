"""
brick_indicator.py — 砖型图核心指标计算模块（纯 NumPy 实现，无 numba 依赖）

提供通用指标计算方法，可被评分引擎和其他模块调用。
移植自 StockTradebyZ/pipeline/Selector.py 的砖型图实现。
"""
from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np
import pandas as pd


# =============================================================================
# 砖型图核心计算
# =============================================================================

def _compute_brick_raw(
    high: np.ndarray, low: np.ndarray, close: np.ndarray,
    n: int, m1: int, m2: int, m3: int,
    t: float, shift1: float, shift2: float,
    sma_w1: int, sma_w2: int, sma_w3: int,
) -> np.ndarray:
    """砖型图核心计算（纯 NumPy，精确复刻 numba 版 shifted EMA 逻辑）。

    参数与 Selector.py _compute_brick_numba() 完全一致。
    返回 brick 值数组（红柱 > 0，绿柱 < 0）。
    """
    length = len(close)

    # ── Step 1: 滚动高低点 ──
    hhv = np.empty(length, dtype=np.float64)
    llv = np.empty(length, dtype=np.float64)
    for i in range(length):
        start = max(0, i - n + 1)
        h_max = high[start]
        l_min = low[start]
        for j in range(start + 1, i + 1):
            if high[j] > h_max:
                h_max = high[j]
            if low[j] < l_min:
                l_min = low[j]
        hhv[i] = h_max
        llv[i] = l_min

    # ── Step 2: VAR2A 空方力量线 ──
    a1 = sma_w1 / m1
    b1 = 1.0 - a1
    var2a = np.empty(length, dtype=np.float64)
    for i in range(length):
        rng = hhv[i] - llv[i]
        if rng == 0.0:
            rng = 0.01
        v1 = (hhv[i] - close[i]) / rng * 100.0 - shift1
        if i == 0:
            var2a[i] = v1 + shift2
        else:
            var2a[i] = a1 * v1 + b1 * (var2a[i - 1] - shift2) + shift2

    # ── Step 3: VAR5A 多方力量线（双重平滑） ──
    a2 = sma_w2 / m2
    b2 = 1.0 - a2
    a3 = sma_w3 / m3
    b3 = 1.0 - a3
    var4a = np.empty(length, dtype=np.float64)
    var5a = np.empty(length, dtype=np.float64)
    for i in range(length):
        rng = hhv[i] - llv[i]
        if rng == 0.0:
            rng = 0.01
        v3 = (close[i] - llv[i]) / rng * 100.0
        if i == 0:
            var4a[i] = v3
            var5a[i] = v3 + shift2
        else:
            var4a[i] = a2 * v3 + b2 * var4a[i - 1]
            var5a[i] = a3 * var4a[i] + b3 * (var5a[i - 1] - shift2) + shift2

    # ── Step 4: Raw = max(diff - t, 0) ──
    raw = np.empty(length, dtype=np.float64)
    for i in range(length):
        diff = var5a[i] - var2a[i]
        raw[i] = diff - t if diff > t else 0.0

    # ── Step 5: Brick = Raw 的一阶差分 ──
    brick = np.zeros(length, dtype=np.float64)
    for i in range(1, length):
        brick[i] = raw[i] - raw[i - 1]

    return brick


def compute_brick_chart(
    df: pd.DataFrame,
    *,
    n: int = 4,
    m1: int = 4,
    m2: int = 6,
    m3: int = 6,
    t: float = 4.0,
    shift1: float = 90.0,
    shift2: float = 100.0,
    sma_w1: int = 1,
    sma_w2: int = 1,
    sma_w3: int = 1,
) -> pd.Series:
    """砖型图红绿柱计算。

    Args:
        df: 日线数据，须包含 high/low/close 列
        n: HHV/LLV 滚动窗口
        m1: 空方线平滑周期
        m2: 多方一阶平滑周期
        m3: 多方二阶平滑周期
        t: 多空差裁剪阈值
        shift1: 空方线平移量
        shift2: 坐标平移量
        sma_w1/w2/w3: SMA 权重

    Returns:
        brick Series（红柱 > 0，绿柱 < 0），index 同 df
    """
    if df.empty or len(df) < 5:
        return pd.Series(np.nan, index=df.index, name="brick")

    arr = _compute_brick_raw(
        df["high"].to_numpy(dtype=np.float64),
        df["low"].to_numpy(dtype=np.float64),
        df["close"].to_numpy(dtype=np.float64),
        n, m1, m2, m3,
        float(t), float(shift1), float(shift2),
        sma_w1, sma_w2, sma_w3,
    )
    return pd.Series(arr, index=df.index, name="brick")


# ── 连续绿柱计数 ──

def green_run(brick_vals: np.ndarray) -> np.ndarray:
    """green_run[i] = 截至 i-1 连续绿柱根数（brick < 0）。"""
    n = len(brick_vals)
    out = np.zeros(n, dtype=np.int32)
    for i in range(1, n):
        if brick_vals[i - 1] < 0.0:
            out[i] = out[i - 1] + 1
        else:
            out[i] = 0
    return out


# ── brick_growth 计算 ──

def compute_brick_growth(
    df: pd.DataFrame,
    brick_col: str = "brick",
) -> float:
    """计算今日 brick_growth = brick[-1] / |brick[-2]|。

    仅当 brick[-1] > 0 且 brick[-2] < 0 时返回有效值。
    """
    if brick_col not in df.columns:
        return float("nan")
    vals = df[brick_col].to_numpy(dtype=float)
    if len(vals) < 3:
        return float("nan")
    b0, b1 = vals[-1], vals[-2]
    if b0 > 0 and b1 < 0:
        return b0 / abs(b1)
    return float("nan")


# =============================================================================
# 知行线计算
# =============================================================================

def compute_zx_lines(
    df: pd.DataFrame,
    m1: int = 14,
    m2: int = 28,
    m3: int = 57,
    m4: int = 114,
    zxdq_span: int = 10,
) -> Tuple[pd.Series, pd.Series]:
    """知行线计算。

    Args:
        df: 日线数据，须包含 close 列
        m1-m4: zxdkx 四条均线周期
        zxdq_span: 双指数平滑 span

    Returns:
        (zxdq, zxdkx) — 短期线、长期线 Series
    """
    close = df["close"].astype(float)
    zxdq = close.ewm(span=zxdq_span, adjust=False).mean().ewm(
        span=zxdq_span, adjust=False
    ).mean()
    zxdkx = (
        close.rolling(m1, min_periods=m1).mean()
        + close.rolling(m2, min_periods=m2).mean()
        + close.rolling(m3, min_periods=m3).mean()
        + close.rolling(m4, min_periods=m4).mean()
    ) / 4.0
    return zxdq, zxdkx


# =============================================================================
# 周线辅助
# =============================================================================

def compute_weekly_close(df: pd.DataFrame) -> pd.Series:
    """日线 → 周线收盘价（每周最后一个实际交易日）。

    按 ISO 周编号分组取最后一行，index 为真实交易日日期。
    """
    if isinstance(df.index, pd.DatetimeIndex):
        close = df["close"].astype(float)
        idx = close.index
    else:
        close = df.set_index(pd.to_datetime(df["date"]))["close"].astype(float)
        idx = close.index
    year_week = (
        idx.isocalendar().year.astype(str)
        + "-"
        + idx.isocalendar().week.astype(str).str.zfill(2)
    )
    weekly = close.groupby(year_week).last()
    last_date_per_week = close.groupby(year_week).apply(
        lambda s: s.index[-1]
    )
    weekly.index = pd.DatetimeIndex(last_date_per_week.values)
    return weekly.dropna()


def compute_weekly_ma_bull(
    df: pd.DataFrame,
    ma_periods: Tuple[int, int, int] = (5, 10, 20),
) -> pd.Series:
    """周线均线多头排列标志（MA_short > MA_mid > MA_long）。

    返回 bool Series，forward-fill 到日线 index。
    """
    weekly_close = compute_weekly_close(df)
    s, m, l = ma_periods
    ma_s = weekly_close.rolling(s, min_periods=s).mean()
    ma_m = weekly_close.rolling(m, min_periods=m).mean()
    ma_l = weekly_close.rolling(l, min_periods=l).mean()
    bull = (ma_s > ma_m) & (ma_m > ma_l)

    daily_index = (
        df.index
        if isinstance(df.index, pd.DatetimeIndex)
        else pd.DatetimeIndex(df["date"])
    )
    bull_daily = (
        bull.astype(float)
        .reindex(daily_index)
        .ffill()
        .fillna(0.0)
        .astype(bool)
    )
    return bull_daily


# =============================================================================
# KDJ 计算（通用辅助）
# =============================================================================

def compute_kdj(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    """KDJ 指标计算（标准初始化：前 n-1 天 K=D=J=50.0）。

    返回带 K/D/J 列的 DataFrame。
    """
    if df.empty:
        return df.assign(K=np.nan, D=np.nan, J=np.nan)
    low_n = df["low"].rolling(window=n, min_periods=n).min()
    high_n = df["high"].rolling(window=n, min_periods=n).max()
    rsv = (
        (df["close"] - low_n) / (high_n - low_n + 1e-9) * 100
    ).to_numpy(dtype=np.float64)

    K = np.full_like(rsv, 50.0)
    D = np.full_like(rsv, 50.0)
    # 前 n-1 天保持 50.0（标准初始化），从第 n 天开始递推
    for i in range(n - 1, len(rsv)):
        K[i] = 2.0 / 3.0 * K[i - 1] + 1.0 / 3.0 * rsv[i]
        D[i] = 2.0 / 3.0 * D[i - 1] + 1.0 / 3.0 * K[i]
    J = 3.0 * K - 2.0 * D

    return df.assign(K=K, D=D, J=J)


# =============================================================================
# K线形态辅助函数
# =============================================================================


def find_first_red_brick_idx(brick: pd.Series) -> int:
    """定位第一块红砖（从绿翻红）的索引。

    从序列末尾向前扫描，找到 brick[i] > 0 且 brick[i-1] < 0 的位置。
    返回该索引 i；找不到时返回 -1。
    """
    bv = brick.to_numpy(dtype=float)
    for i in range(len(bv) - 1, 0, -1):
        if bv[i] > 0 and bv[i - 1] < 0:
            return i
    return -1


def compute_upper_shadow_ratio(df: pd.DataFrame, idx: int) -> float:
    """计算指定行 K 线的上影线占实体比例。

    Args:
        df: 含 open/close/high/low 列的日线 DataFrame
        idx: K 线行索引

    Returns:
        upper_shadow / body，实体为 0 时用 (high - low) 做分母，
        idx 无效或无法计算时返回 NaN
    """
    if idx < 0 or idx >= len(df):
        return float("nan")
    row = df.iloc[idx]
    try:
        high, close, open_ = float(row["high"]), float(row["close"]), float(row["open"])
    except (KeyError, ValueError):
        return float("nan")
    body = abs(close - open_)
    shadow = high - max(open_, close)
    denom = body if body > 0 else (high - float(row["low"]))
    if denom <= 0 or not np.isfinite(denom):
        return float("nan")
    return shadow / denom
