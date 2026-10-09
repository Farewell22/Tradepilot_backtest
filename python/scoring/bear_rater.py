"""熊市评分引擎：周线视角 + KDJ共振 + 严格止盈止损。"""
from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

import pandas as pd
import yaml

from python.scoring.stock_rater import (
    RatingResult,
    calc_kdj,
    calc_ma,
    calc_position,
    calc_volume_ratio,
    get_grade,
    signal_bonus,
)


def load_bear_config(config_path: str | None = None) -> dict:
    if config_path is None:
        from pathlib import Path
        config_path = str(Path(__file__).resolve().parent.parent / "config" / "bear_strategy.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _detect_weekly_swing_points(
    highs: List[float], lows: List[float],
    left: int = 3, right: int = 3,
) -> tuple[list, list]:
    """检测周线级别的局部高低点。"""
    from python.scoring.stock_rater import detect_swing_points
    return detect_swing_points(highs, lows, left, right)


def score_weekly_trend(weekly_closes, weekly_ma5, weekly_ma10, weekly_ma20, w_idx: int) -> int:
    """周线趋势评分（权重 35%）：多头排列满分。"""
    if w_idx < 5:
        return 50
    m5 = weekly_ma5[w_idx]
    m10 = weekly_ma10[w_idx]
    m20 = weekly_ma20[w_idx]
    if any(v is None for v in (m5, m10, m20)):
        return 50
    if m5 > m10 > m20:
        return 95
    if m5 > m10:
        return 75
    if m5 > m20:
        return 55
    return 30


def score_kdj_resonance(
    daily_closes, daily_highs, daily_lows,
    weekly_closes, weekly_highs, weekly_lows,
    idx: int, w_idx: int,
) -> int:
    """KDJ 共振评分（权重 20%）：周线 + 日线 J 值同时 < 13 满分。"""
    if idx < 9 or w_idx < 9:
        return 50

    _, _, daily_j = calc_kdj(daily_highs, daily_lows, daily_closes)
    _, _, weekly_j = calc_kdj(weekly_highs, weekly_lows, weekly_closes)

    d_j = daily_j[idx] if idx < len(daily_j) else 50
    w_j = weekly_j[w_idx] if w_idx < len(weekly_j) else 50

    score = 30
    if w_j < 13:
        score += 35
    if d_j < 13:
        score += 35
    return min(100, score)


def score_monthly_kdj_bonus(
    monthly_closes, monthly_highs, monthly_lows,
    m_idx: int,
) -> int:
    """月线 KDJ 超卖加成：J < 13 加 50 分，J < -5 加 100 分。"""
    if m_idx < 9:
        return 0
    _, _, monthly_j = calc_kdj(monthly_highs, monthly_lows, monthly_closes)
    m_j = monthly_j[m_idx] if m_idx < len(monthly_j) else 50
    if m_j < -5:
        return 100
    if m_j < 13:
        return 50
    return 0


def rate_bear_stocks(
    stocks_data: List[dict],
    config: dict | None = None,
) -> List[RatingResult]:
    """熊市批量评分（FastAPI 入口兼容）。"""
    if config is None:
        config = load_bear_config()
    weights = config.get("bear_weights", {})

    results = []
    for stock in stocks_data:
        code = stock["code"]
        klines = stock.get("klines", [])

        if len(klines) < 60:
            continue

        if isinstance(klines, pd.DataFrame):
            closes = klines["close"].tolist()
            highs = klines["high"].tolist()
            lows = klines["low"].tolist()
            volumes = klines["vol"].tolist()
            dates = [d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d)[:4]+"-"+str(d)[4:6]+"-"+str(d)[6:8] for d in klines.index]
        else:
            closes = [float(r["close"]) for r in klines]
            highs = [float(r["high"]) for r in klines]
            lows = [float(r["low"]) for r in klines]
            volumes = [float(r["volume"]) for r in klines]
        idx = len(closes) - 1

        # 周线聚合
        w_closes, w_highs, w_lows = _daily_to_weekly_ohlcv(closes, highs, lows, dates)
        if len(w_closes) < 5:
            continue
        w_idx = len(w_closes) - 1

        # 周线趋势
        w_ma5 = calc_ma(w_closes, 5)
        w_ma10 = calc_ma(w_closes, 10)
        w_ma20 = calc_ma(w_closes, 20)
        s_weekly = score_weekly_trend(w_closes, w_ma5, w_ma10, w_ma20, w_idx)

        # 日线位置
        lookback = min(60, idx)
        d_high = max(highs[idx - lookback: idx + 1])
        d_low = min(lows[idx - lookback: idx + 1])
        pos_pct = calc_position(closes[idx], d_high, d_low)
        s_pos = _score_daily_position(pos_pct)

        # KDJ 共振
        s_kdj = score_kdj_resonance(closes, highs, lows, w_closes, w_highs, w_lows, idx, w_idx)

        # 月线 KDJ 加成
        m_closes, m_highs, m_lows = _daily_to_monthly_ohlcv(closes, highs, lows, dates)
        m_idx = len(m_closes) - 1 if m_closes else 0
        s_monthly = score_monthly_kdj_bonus(m_closes, m_highs, m_lows, m_idx)

        # 量价行为
        s_vol = _score_bear_volume(volumes, closes, idx)

        # N 型结构
        s_n = _score_weekly_n(highs, lows, idx)

        total = (
            s_weekly * weights.get("weekly_trend", 0.35)
            + s_pos * weights.get("daily_position", 0.20)
            + s_kdj * weights.get("kdj_resonance", 0.20)
            + s_monthly * weights.get("monthly_kdj_bonus", 0.10)
            + s_vol * weights.get("volume_behavior", 0.10)
            + s_n * weights.get("n_structure", 0.05)
        )
        total = max(0, min(100, round(total, 1)))

        thresholds = config.get("bear_thresholds", {})
        pass_threshold = thresholds.get("pass", 70)

        # 信号检测
        sig_type, sig_name = "其他", "熊市B1"
        _, _, j_vals = calc_kdj(highs, lows, closes)
        if j_vals[idx] < -10:
            sig_name = "熊市超卖"

        change_pct = (closes[idx] - closes[idx - 1]) / closes[idx - 1] * 100 if idx > 0 else 0.0

        result = RatingResult(
            code=code,
            close=closes[idx],
            change_pct=round(change_pct, 2),
            vol_ratio=calc_volume_ratio(volumes, idx),
            position_pct=round(pos_pct, 1),
            total=total,
            grade=get_grade(total),
            verdict="PASS" if total >= pass_threshold else "WATCH" if total >= 60 else "FAIL",
            signal_type=sig_type,
            signal_name=sig_name,
            trend=s_weekly,
            position=s_pos,
            volume=s_vol,
            abnormal=50,
            rr_score=50,
            bonus=s_monthly,
            stop=closes[idx] * 0.99,
            target=closes[idx] * 1.07,
            rr_ratio=1.0,
            comment=f"周线趋势{s_weekly}, KDJ共振{s_kdj}, 月线加成{s_monthly}",
        )
        results.append(result)

    results.sort(key=lambda r: r.total, reverse=True)
    for i, r in enumerate(results):
        r.rank = i + 1
    return results


def _daily_to_weekly_ohlcv(
    closes: list, highs: list, lows: list, klines=None,
) -> tuple[list, list, list]:
    """日线聚合为周线 OHLC。"""
    if klines and hasattr(klines[0], 'date'):
        dates = [r.date for r in klines]
    else:
        dates = [f"2026-{i//5+1:02d}-{i%28+1:02d}" for i in range(len(closes))]

    w_closes, w_highs, w_lows = [], [], []
    prev_week = None
    week_closes, week_highs, week_lows = [], [], []

    for i, d in enumerate(dates):
        try:
            from datetime import datetime
            dt = datetime.strptime(d, "%Y-%m-%d")
            wk = dt.isocalendar()[1]
        except (ValueError, AttributeError):
            wk = i // 5  # fallback

        if wk != prev_week and prev_week is not None:
            if week_closes:
                w_closes.append(week_closes[-1])
                w_highs.append(max(week_highs))
                w_lows.append(min(week_lows))
            week_closes, week_highs, week_lows = [], [], []

        week_closes.append(closes[i])
        week_highs.append(highs[i])
        week_lows.append(lows[i])
        prev_week = wk

    # 最后一周
    if week_closes:
        w_closes.append(week_closes[-1])
        w_highs.append(max(week_highs))
        w_lows.append(min(week_lows))

    return w_closes, w_highs, w_lows


def _daily_to_monthly_ohlcv(
    closes: list, highs: list, lows: list, klines=None,
) -> tuple[list, list, list]:
    """日线聚合为月线 OHLC。"""
    if klines and hasattr(klines[0], 'date'):
        dates = [r.date for r in klines]
    else:
        dates = [f"2026-{i//20+1:02d}-{i%28+1:02d}" for i in range(len(closes))]

    m_closes, m_highs, m_lows = [], [], []
    prev_month = None
    month_closes, month_highs, month_lows = [], [], []

    for i, d in enumerate(dates):
        try:
            from datetime import datetime
            dt = datetime.strptime(d, "%Y-%m-%d")
            mo = dt.month
        except (ValueError, AttributeError):
            mo = i // 20

        if mo != prev_month and prev_month is not None:
            if month_closes:
                m_closes.append(month_closes[-1])
                m_highs.append(max(month_highs))
                m_lows.append(min(month_lows))
            month_closes, month_highs, month_lows = [], [], []

        month_closes.append(closes[i])
        month_highs.append(highs[i])
        month_lows.append(lows[i])
        prev_month = mo

    if month_closes:
        m_closes.append(month_closes[-1])
        m_highs.append(max(month_highs))
        m_lows.append(min(month_lows))

    return m_closes, m_highs, m_lows


def _score_daily_position(pos_pct: float) -> int:
    if pos_pct < 25:
        return 92
    if pos_pct < 40:
        return 82
    if pos_pct < 55:
        return 72
    if pos_pct < 70:
        return 62
    if pos_pct < 80:
        return 52
    return 30


def _score_bear_volume(volumes, closes, idx: int) -> int:
    if idx < 10:
        return 50
    up_v, down_v = [], []
    for i in range(max(0, idx - 10), idx + 1):
        (up_v if i == 0 or closes[i] > closes[i - 1] else down_v).append(volumes[i])
    ratio = sum(up_v) / max(1, sum(down_v)) if down_v else 2.0
    if ratio >= 2.0:
        return 92
    if ratio >= 1.5:
        return 83
    if ratio >= 1.2:
        return 73
    if ratio >= 0.9:
        return 62
    return 42


def _score_weekly_n(highs, lows, idx: int) -> int:
    """周线级别的 N 型结构检测。"""
    if idx < 30:
        return 50
    peaks, valleys = _detect_weekly_swing_points(highs[:idx + 1], lows[:idx + 1])
    if not peaks:
        return 50
    last_peak = peaks[-1]
    pullback_low = min(lows[last_peak["idx"]:idx + 1])
    pullback_pct = (last_peak["price"] - pullback_low) / last_peak["price"] * 100
    if 10 <= pullback_pct <= 30:
        return 80
    if 5 <= pullback_pct <= 40:
        return 60
    return 40
