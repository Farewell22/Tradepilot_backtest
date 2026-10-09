# -*- coding: utf-8 -*-
"""
Z哥战法股票批量评分引擎

移植自 B1_Stock_rate/Stock_rater 的 5 维度评分版本。
支持 CLI 调用和 FastAPI 集成。
"""
from __future__ import annotations

import csv
import json
import logging
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "stock_rater.yaml"

logger = logging.getLogger("stock_rater")

# ── 数据结构 ──────────────────────────────────────────────


@dataclass
class KLineRow:
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float


@dataclass
class RatingResult:
    rank: int = 0
    code: str = ""
    close: float = 0.0
    change_pct: float = 0.0
    vol_ratio: float = 1.0
    position_pct: float = 50.0
    trend: int = 50
    position: int = 50
    volume: int = 50
    abnormal: int = 50
    rr_score: int = 50
    bonus: int = 0
    total: float = 0.0
    grade: str = "C"
    verdict: str = "FAIL"
    signal_type: str = "其他"
    signal_name: str = "趋势疲弱"
    stop: float = 0.0
    target: float = 0.0
    rr_ratio: float = 1.0
    comment: str = ""
    industry: str = ""
    sub_industry: str = ""
    fail_reasons: list = field(default_factory=list)


# ── 配置加载 ──────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "trend": 0.15,
    "position": 0.15,
    "volume": 0.25,
    "abnormal": 0.25,
    "risk_reward": 0.20,
}


def load_config(config_path: Path = _CONFIG_PATH) -> dict:
    if not config_path.exists():
        return {"weights": DEFAULT_WEIGHTS}
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if "weights" not in cfg:
        cfg["weights"] = DEFAULT_WEIGHTS
    return cfg


# ── CSV读取 ──────────────────────────────────────────────


def read_csv(filepath: Path) -> List[KLineRow]:
    rows = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(KLineRow(
                date=row["date"],
                open=float(row["open"]),
                close=float(row["close"]),
                high=float(row["high"]),
                low=float(row["low"]),
                volume=float(row["volume"]),
            ))
    return rows


# ── 技术指标 ──────────────────────────────────────────────


def calc_ma(values: List[float], period: int) -> List[Optional[float]]:
    result: List[Optional[float]] = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(values[i - period + 1: i + 1]) / period)
    return result


def calc_ma_slope(ma_values: List[Optional[float]], idx: int, period: int = 3) -> float:
    if idx < period or ma_values[idx] is None or ma_values[idx - period] is None:
        return 0.0
    prev = ma_values[idx - period]
    if prev == 0:
        return 0.0
    return (ma_values[idx] - prev) / prev * 100


def calc_volume_ratio(volumes: List[float], idx: int, period: int = 5) -> float:
    if idx < period:
        return 1.0
    avg_vol = sum(volumes[idx - period: idx]) / period
    return volumes[idx] / avg_vol if avg_vol > 0 else 1.0


def calc_position(close: float, range_high: float, range_low: float) -> float:
    if range_high == range_low:
        return 50.0
    return (close - range_low) / (range_high - range_low) * 100


def calc_kdj(highs: List[float], lows: List[float], closes: List[float],
             period: int = 9) -> Tuple[List[float], List[float], List[float]]:
    k_vals, d_vals, j_vals = [], [], []
    prev_k, prev_d = 50.0, 50.0
    for i in range(len(closes)):
        if i < period - 1:
            k_vals.append(50.0)
            d_vals.append(50.0)
            j_vals.append(50.0)
            continue
        high_n = max(highs[i - period + 1: i + 1])
        low_n = min(lows[i - period + 1: i + 1])
        rsv = (closes[i] - low_n) / (high_n - low_n) * 100 if high_n != low_n else 50.0
        k = 2 / 3 * prev_k + 1 / 3 * rsv
        d = 2 / 3 * prev_d + 1 / 3 * k
        j = 3 * k - 2 * d
        prev_k, prev_d = k, d
        k_vals.append(k)
        d_vals.append(d)
        j_vals.append(j)
    return k_vals, d_vals, j_vals


# ── 四维度评分 ──────────────────────────────────────────


def score_trend(closes: List[float], ma5: list, ma10: list, ma20: list, idx: int) -> int:
    if idx < 20:
        return 50

    ma5_v = ma5[idx]
    ma10_v = ma10[idx]
    ma20_v = ma20[idx]
    if ma5_v is None or ma10_v is None or ma20_v is None:
        return 50

    slope5 = calc_ma_slope(ma5, idx, 3)
    slope10 = calc_ma_slope(ma10, idx, 3)

    # 均线排列基础分
    if ma5_v > ma10_v > ma20_v:
        score = 85
    elif ma5_v > ma10_v and ma10_v > ma20_v * 0.99:
        score = 75
    elif ma5_v > ma10_v:
        score = 65
    elif ma5_v < ma10_v and ma10_v < ma20_v:
        score = 30
    elif ma5_v < ma10_v:
        score = 45
    else:
        score = 50

    # MA5斜率调整
    score += min(15, int(slope5 / 0.5) * 5) if slope5 > 0 else -min(15, int(abs(slope5) / 0.5) * 5)

    # MA10斜率辅助
    score += 3 if slope10 > 1 else (-3 if slope10 < -1 else 0)

    # 价格与MA5关系
    if idx >= 3:
        above = sum(1 for i in range(idx - 2, idx + 1) if closes[i] > ma5[i])
        score += 5 if above >= 3 else (-5 if above == 0 else 0)

    return max(0, min(100, score))


def score_position(close: float, position_pct: float, recent_high: float) -> int:
    if position_pct < 25:
        score = 92
    elif position_pct < 40:
        score = 82
    elif position_pct < 55:
        score = 72
    elif position_pct < 70:
        score = 62
    elif position_pct < 80:
        score = 52
    elif position_pct < 90:
        score = 42
    else:
        score = 30

    if recent_high > 0:
        upside = (recent_high - close) / close * 100
        score += 3 if upside > 30 else (-5 if upside < 5 else 0)

    return max(0, min(100, score))


def score_volume(volumes: List[float], closes: List[float], idx: int) -> int:
    if idx < 10:
        return 50

    # 涨跌量比
    up_vols, down_vols = [], []
    for i in range(max(0, idx - 10), idx + 1):
        (up_vols if (i == 0 or closes[i] > closes[i - 1]) else down_vols).append(volumes[i])

    avg_up = sum(up_vols) / len(up_vols) if up_vols else 0
    avg_down = sum(down_vols) / len(down_vols) if down_vols else 1
    ratio = avg_up / avg_down if avg_down > 0 else 2.0

    if ratio >= 2.0:
        score = 92
    elif ratio >= 1.5:
        score = 83
    elif ratio >= 1.2:
        score = 73
    elif ratio >= 0.9:
        score = 62
    elif ratio >= 0.7:
        score = 52
    elif ratio >= 0.5:
        score = 42
    else:
        score = 32

    # 最大量K线是否为阳线
    recent_vols = volumes[max(0, idx - 10): idx + 1]
    if recent_vols:
        max_local = recent_vols.index(max(recent_vols))
        actual = max(0, idx - 10) + max_local
        if actual > 0:
            score += 5 if closes[actual] >= closes[actual - 1] else -10

    # 放量大阴线检测
    avg_vol_10 = sum(volumes[max(0, idx - 10): idx]) / max(1, idx - max(0, idx - 10))
    for i in range(max(1, idx - 4), idx + 1):
        if volumes[i] > avg_vol_10 * 2 and closes[i] < closes[i - 1]:
            score -= 10
            break

    # 最后一天缩量
    if idx >= 5:
        avg5 = sum(volumes[idx - 5: idx]) / 5
        if volumes[idx] < avg5 * 0.8:
            score += 3

    return max(0, min(100, score))


def score_abnormal(closes: List[float], volumes: List[float],
                   highs: List[float], lows: List[float], idx: int) -> int:
    if idx < 10:
        return 50

    lookback = min(60, idx)
    range_low = min(lows[idx - lookback: idx + 1])
    total_rise = (closes[idx] - range_low) / range_low * 100 if range_low > 0 else 0

    avg_vol_20 = sum(volumes[max(0, idx - 20): idx]) / min(20, idx) if idx > 0 else 1
    abnormal_days = 0
    max_vol_ratio = 0.0

    for i in range(max(0, idx - lookback), idx + 1):
        vr = volumes[i] / avg_vol_20 if avg_vol_20 > 0 else 1
        max_vol_ratio = max(max_vol_ratio, vr)
        if vr > 2.0 and (i == 0 or closes[i] > closes[i - 1]):
            abnormal_days += 1

    # 基于涨幅
    if total_rise > 100:
        score = 25
    elif total_rise > 80:
        score = 38
    elif total_rise > 60:
        score = 50
    elif total_rise > 50:
        score = 58
    elif total_rise > 40:
        score = 65
    elif total_rise > 30:
        score = 72
    elif total_rise > 25:
        score = 78
    else:
        score = 85

    # 异常放量天数
    if abnormal_days >= 3:
        score += 12
    elif abnormal_days >= 2:
        score += 8
    elif abnormal_days >= 1:
        score += 4

    if max_vol_ratio > 3:
        score += 5

    # 高位放量阴线扣分
    range_high = max(highs[max(0, idx - lookback): idx + 1])
    for i in range(max(1, max(0, idx - 10)), idx + 1):
        if volumes[i] > avg_vol_20 * 2 and closes[i] < closes[i - 1]:
            if closes[i] > range_low * 1.3:
                score -= 10
                break

    return max(0, min(100, score))


# ── 盈亏比评分 ──────────────────────────────────────────


def score_risk_reward(rr_ratio: float) -> int:
    if rr_ratio >= 5:
        return 95
    elif rr_ratio >= 4:
        return 85
    elif rr_ratio >= 3:
        return 75
    elif rr_ratio >= 2:
        return 65
    elif rr_ratio >= 1.5:
        return 55
    elif rr_ratio >= 1:
        return 40
    else:
        return 20


# ── 信号识别 ──────────────────────────────────────────────


def identify_signal(rows: List[KLineRow], closes: List[float], volumes: List[float],
                    highs: List[float], lows: List[float], idx: int) -> Tuple[str, str]:
    if idx < 15:
        return "其他", "趋势疲弱"

    avg_vol_5 = sum(volumes[max(0, idx - 5): idx]) / min(5, idx) if idx > 0 else 1
    cur_vr = volumes[idx] / avg_vol_5 if avg_vol_5 > 0 else 1
    daily_chg = (closes[idx] - closes[idx - 1]) / closes[idx - 1] * 100 if idx > 0 else 0

    lookback = min(30, idx)
    avg_vol_lb = sum(volumes[max(0, idx - lookback): idx]) / lookback
    has_abnormal = False
    abnormal_idx = -1

    for i in range(max(0, idx - lookback), idx):
        vr = volumes[i] / avg_vol_lb if avg_vol_lb > 0 else 1
        if vr > 1.8 and (i == 0 or closes[i] > closes[i - 1]):
            has_abnormal = True
            abnormal_idx = i

    range_high = max(highs[max(0, idx - lookback): idx + 1])
    range_low = min(lows[max(0, idx - lookback): idx + 1])
    position = calc_position(closes[idx], range_high, range_low)

    # ── B2检测（优先） ──
    if has_abnormal and daily_chg >= 4.0 and cur_vr >= 1.5:
        if cur_vr >= 2.0:
            return "B2", "倍量起爆"

        # 平行重炮
        for i in range(max(0, idx - 15), idx):
            vr = volumes[i] / avg_vol_lb if avg_vol_lb > 0 else 1
            if vr > 1.5 and abs(closes[i] - closes[idx]) / closes[idx] < 0.1:
                mid_min = min(closes[i + 1: idx]) if i + 1 < idx else closes[i]
                if mid_min < closes[i] * 0.97:
                    return "B2", "平行重炮"

        # 跃跃欲试
        if lookback >= 15:
            rr = (range_high - range_low) / range_low * 100 if range_low > 0 else 100
            if rr < 15:
                return "B2", "跃跃欲试"

        # 灾后重建
        if idx >= 3 and lows[idx - 2] < range_low * 1.02 and closes[idx] > closes[idx - 1]:
            return "B2", "灾后重建"

        return "B2", "B2启动"

    # ── B1检测 ──
    is_shrinking = cur_vr < 0.8
    if has_abnormal and is_shrinking and position < 65:
        pre_low = min(lows[max(0, abnormal_idx - 5): abnormal_idx + 1]) if abnormal_idx >= 0 else lows[0]

        # 连续缩量
        shrink_days = 0
        for i in range(idx, max(0, idx - 5), -1):
            vr_i = volumes[i] / (sum(volumes[max(0, i - 5): i]) / min(5, i)) if i > 0 else 1
            if vr_i < 0.8:
                shrink_days += 1
            else:
                break

        _, _, j_vals = calc_kdj(highs, lows, closes)
        j_val = j_vals[idx]

        # N型结构
        n_struct = False
        if abnormal_idx > 0:
            rise_high = max(highs[max(0, abnormal_idx - 3): abnormal_idx + 1])
            pre_rise_low = min(lows[max(0, abnormal_idx - 5): abnormal_idx])
            if pre_rise_low * 0.95 < closes[idx] < rise_high:
                n_struct = True

        if shrink_days >= 4 and j_val < -10 and n_struct:
            return "B1", "超级B1"

        if n_struct or closes[idx] < range_low * 1.05:
            return "B1", "B1潜伏"

        return "B1", "B1潜伏"

    # ── 其他信号 ──
    if daily_chg > 0 and cur_vr > 1.2:
        return "其他", "反弹机会"
    if position > 70:
        return "其他", "出货风险"
    return "其他", "趋势疲弱"


# ── 止损止盈 ──────────────────────────────────────────────


def calc_stop_target(rows: List[KLineRow], closes: List[float],
                     highs: List[float], lows: List[float],
                     method: str, idx: int) -> Tuple[float, float, float]:
    if idx < 5:
        return closes[idx] * 0.95, closes[idx] * 1.10, 1.0

    lookback = min(30, idx)
    recent_low = min(lows[max(0, idx - lookback): idx + 1])
    recent_high = max(highs[max(0, idx - lookback): idx + 1])
    current = closes[idx]

    if method == "B1":
        stop = recent_low * 0.96
        target = recent_high
    elif method == "B2":
        stop = rows[idx].open
        target = recent_high * 1.1
    else:
        stop = recent_low * 0.97
        target = (current + recent_high) / 2

    risk = current - stop
    reward = target - current
    rr = reward / risk if risk > 0 else 0
    return round(stop, 2), round(target, 2), round(rr, 2)


# ── 信号加成 ──────────────────────────────────────────────


def signal_bonus(rows: List[KLineRow], closes: List[float], volumes: List[float],
                 highs: List[float], lows: List[float],
                 signal_type: str, signal_name: str, idx: int) -> int:
    bonus = 0

    if signal_type == "B1":
        avg_vol_5 = sum(volumes[max(0, idx - 5): idx]) / min(5, idx) if idx > 0 else 1
        vr = volumes[idx] / avg_vol_5 if avg_vol_5 > 0 else 1
        if vr < 0.7:
            bonus += 5

        if idx >= 3:
            shrink = 0
            for i in range(idx, max(0, idx - 5), -1):
                vr_i = volumes[i] / (sum(volumes[max(0, i - 5): i]) / min(5, i)) if i > 0 else 1
                if vr_i < 0.8:
                    shrink += 1
            if shrink >= 3:
                bonus += 3

        _, _, j_vals = calc_kdj(highs, lows, closes)
        if j_vals[idx] < -10:
            bonus += 3

        if signal_name == "超级B1":
            bonus += 8

    elif signal_type == "B2":
        daily = (closes[idx] - closes[idx - 1]) / closes[idx - 1] * 100 if idx > 0 else 0
        avg_vol_5 = sum(volumes[max(0, idx - 5): idx]) / min(5, idx) if idx > 0 else 1
        vr = volumes[idx] / avg_vol_5 if avg_vol_5 > 0 else 1

        if daily >= 4:
            bonus += 3
        if vr >= 1.5:
            bonus += 5
        if vr >= 2.0:
            bonus += 3
        if rows[idx].close >= rows[idx].high * 0.995:
            bonus += 5
        if signal_name in ("平行重炮", "跃跃欲试", "灾后重建", "倍量起爆"):
            bonus += 5

    return bonus


# ── 评级/判定 ──────────────────────────────────────────────


def get_grade(total: float) -> str:
    if total >= 90:
        return "S"
    elif total >= 80:
        return "A"
    elif total >= 75:
        return "B+"
    elif total >= 70:
        return "B"
    elif total >= 60:
        return "C"
    else:
        return "D"


def get_verdict(total: float, vol_score: int, abnormal_score: int,
                config: Optional[dict] = None) -> str:
    thresholds = (config or {}).get("thresholds", {})
    force_fail = (config or {}).get("force_fail", {})
    pass_threshold = thresholds.get("pass", 75)
    watch_threshold = thresholds.get("watch", 60)
    vol_fail = force_fail.get("volume_below", 40)
    abn_fail = force_fail.get("abnormal_below", 30)

    if vol_score < vol_fail or abnormal_score < abn_fail:
        return "FAIL"
    if total >= pass_threshold:
        return "PASS"
    elif total >= watch_threshold:
        return "WATCH"
    return "FAIL"


def check_volume_pattern(closes, volumes, opens, idx, window=50, ratio_threshold=0.5):
    """绿肥红瘦检查: 阴量总量/阳量总量比值 > threshold 则通过。

    测试逆向思维：要求阴量 > 阳量（绿肥红瘦），即近期下跌放量、
    上涨缩量，可能是恐慌盘出清后的底部信号。
    """
    if idx < window:
        return True, 0.0
    start = max(1, idx - window + 1)
    up_vols, down_vols = [], []
    for i in range(start, idx + 1):
        if closes[i] > opens[i]:
            up_vols.append(volumes[i])
        elif closes[i] < opens[i]:
            down_vols.append(volumes[i])
    if not up_vols or not down_vols:
        return True, 0.0
    ratio = sum(down_vols) / sum(up_vols) if sum(up_vols) > 0 else 0
    return ratio > ratio_threshold, round(ratio, 3)


def check_s1_pattern(closes, volumes, opens, idx, window=35):
    """防S1形态检查: 如果窗口内最大成交量日是阴线，则拒绝。

    S1形态特征 = 近期最大量日为放量下跌 = 出货信号，不应买入。
    """
    if idx < window:
        return True, None
    start = max(0, idx - window)
    max_vol_idx = start
    max_vol = volumes[start]
    for i in range(start + 1, idx + 1):
        if volumes[i] > max_vol:
            max_vol = volumes[i]
            max_vol_idx = i
    if closes[max_vol_idx] < opens[max_vol_idx]:
        return False, max_vol_idx
    return True, max_vol_idx


# ── 过度上涨后第一次回调过滤器 ────────────────────────────


def check_excessive_runaway(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    volumes: List[float],
    idx: int,
    lookback: int = 120,
    consecutive_days: int = 4,
    daily_gain_pct: float = 7.0,
    short_term_rise_pct: float = 50.0,
    short_term_window: int = 20,
    extreme_rise_pct: float = 150.0,
):
    """检测前期是否存在过度上涨（连板/急涨/极端涨幅）。

    Returns:
        (is_excessive, details)
        details = {
            "max_consecutive": int,
            "total_rise_pct": float,
            "short_term_rise_pct": float,
            "peak_idx": int,
            "hit_reasons": [str],
        }
    """
    if idx < 20:
        return False, {}

    start = max(0, idx - lookback)
    details = {
        "max_consecutive": 0,
        "total_rise_pct": 0.0,
        "short_term_rise_pct": 0.0,
        "peak_idx": idx,
        "hit_reasons": [],
    }

    # 维度1: 连板检测 — 扫描连续涨幅≥daily_gain_pct的最大天数
    max_consecutive = 0
    current_streak = 0
    for i in range(start + 1, idx + 1):
        if closes[i - 1] > 0:
            chg = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
        else:
            chg = 0
        if chg >= daily_gain_pct:
            current_streak += 1
            max_consecutive = max(max_consecutive, current_streak)
        else:
            current_streak = 0
    details["max_consecutive"] = max_consecutive

    if max_consecutive >= consecutive_days:
        details["hit_reasons"].append(
            f"连续{max_consecutive}天大涨≥{daily_gain_pct}%"
        )

    # 维度2: 短期急涨 — short_term_window内的最大涨幅
    short_start = max(0, idx - short_term_window)
    short_high = max(highs[short_start: idx + 1])
    short_low = min(lows[short_start: idx + 1])
    if short_low > 0:
        short_rise = (short_high - short_low) / short_low * 100
        details["short_term_rise_pct"] = round(short_rise, 1)
        if short_rise >= short_term_rise_pct:
            details["hit_reasons"].append(
                f"{short_term_window}日内急涨{short_rise:.0f}%"
            )

    # 维度3: 极端涨幅兜底 — lookback内的总涨幅
    range_high = max(highs[start: idx + 1])
    range_low = min(lows[start: idx + 1])
    if range_low > 0:
        total_rise = (range_high - range_low) / range_low * 100
        details["total_rise_pct"] = round(total_rise, 1)
        if total_rise >= extreme_rise_pct:
            details["hit_reasons"].append(
                f"总涨幅{total_rise:.0f}%≥{extreme_rise_pct}%"
            )

    # 记录波段最高点索引
    peak_rel_idx = highs[start: idx + 1].index(range_high)
    details["peak_idx"] = start + peak_rel_idx

    return len(details["hit_reasons"]) > 0, details


def detect_swing_points(highs: List[float], lows: List[float],
                        left: int = 3, right: int = 3) -> Tuple[List[dict], List[dict]]:
    """检测局部最高点(阻力位)和局部最低点(支撑位)。

    滑动窗口法: high[i]在左右N根K线内为最大值 → 阻力位;
                 low[i]在左右N根K线内为最小值 → 支撑位。

    Returns:
        (peaks, valleys) 各为 [{"idx": int, "price": float}, ...]
    """
    peaks: List[dict] = []
    valleys: List[dict] = []
    n = len(highs)
    for i in range(left, n - right):
        window_highs = highs[i - left: i + right + 1]
        if highs[i] == max(window_highs):
            if not peaks or i - peaks[-1]["idx"] > right:
                peaks.append({"idx": i, "price": highs[i]})
        window_lows = lows[i - left: i + right + 1]
        if lows[i] == min(window_lows):
            if not valleys or i - valleys[-1]["idx"] > right:
                valleys.append({"idx": i, "price": lows[i]})
    return peaks, valleys


def check_first_pullback(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    idx: int,
    peak_idx: int,
    min_bounce_pct: float = 15.0,
):
    """判断当前是否是大涨后的第一次回调。

    从 peak_idx 到当前 idx，用 detect_swing_points 检测谷底数量。
    谷底 ≤ 1 → 第一次回调。

    Returns:
        (is_first_pullback, pullback_count)
    """
    if peak_idx >= idx - 5:
        return False, 0

    segment_highs = highs[peak_idx: idx + 1]
    segment_lows = lows[peak_idx: idx + 1]
    peaks, valleys = detect_swing_points(segment_highs, segment_lows, left=2, right=2)

    pullback_count = len(valleys)

    # 如果最后一个峰比最后一个谷更新 → 正在新一轮回调中
    if peaks:
        last_peak_seg = peaks[-1]["idx"]
        last_valley_seg = valleys[-1]["idx"] if valleys else -1
        if last_peak_seg > last_valley_seg:
            peak_price = segment_highs[last_peak_seg]
            cur_price = closes[idx]
            if peak_price > 0 and (peak_price - cur_price) / peak_price * 100 > 5:
                pullback_count += 1

    # 兜底: 没有谷底但已明显下跌
    if pullback_count == 0:
        peak_price = highs[peak_idx]
        cur_price = closes[idx]
        if peak_price > 0:
            drawdown = (peak_price - cur_price) / peak_price * 100
            if drawdown > 10:
                pullback_count = 1

    return pullback_count <= 1, pullback_count


# ── 单只评分主函数 ────────────────────────────────────────


def rate_one(filepath: Path, weights: dict = None, config: dict = None) -> Optional[RatingResult]:
    if weights is None:
        weights = DEFAULT_WEIGHTS
    rows = read_csv(filepath)
    if len(rows) < 20:
        logger.warning("%s 数据不足20条，跳过", filepath.name)
        return None

    closes = [r.close for r in rows]
    volumes = [r.volume for r in rows]
    highs = [r.high for r in rows]
    lows = [r.low for r in rows]

    idx = len(rows) - 1

    # 龙头预筛：半年涨幅 < 10% 扣 15 分
    leader_penalty = 0
    if idx >= 120:
        rise_120d = (closes[idx] - closes[idx - 120]) / closes[idx - 120] * 100 if closes[idx - 120] > 0 else 0
        if rise_120d < 10:
            leader_penalty = 15

    ma5 = calc_ma(closes, 5)
    ma10 = calc_ma(closes, 10)
    ma20 = calc_ma(closes, 20)

    lookback = min(60, idx)
    range_high = max(highs[max(0, idx - lookback): idx + 1])
    range_low = min(lows[max(0, idx - lookback): idx + 1])
    position_pct = calc_position(closes[idx], range_high, range_low)

    avg_vol_5 = sum(volumes[max(0, idx - 5): idx]) / min(5, idx)
    vol_ratio = volumes[idx] / avg_vol_5 if avg_vol_5 > 0 else 1.0

    # 四维度评分
    s_trend = score_trend(closes, ma5, ma10, ma20, idx)
    s_pos = score_position(closes[idx], position_pct, range_high)
    s_vol = score_volume(volumes, closes, idx)
    s_abn = score_abnormal(closes, volumes, highs, lows, idx)

    # 信号识别
    sig_type, sig_name = identify_signal(rows, closes, volumes, highs, lows, idx)

    # 止损目标
    stop, target, rr_ratio = calc_stop_target(rows, closes, highs, lows, sig_type, idx)
    s_rr = score_risk_reward(rr_ratio)

    # 信号加成
    bonus = signal_bonus(rows, closes, volumes, highs, lows, sig_type, sig_name, idx)

    # 加权总分
    total = (
        s_trend * weights.get("trend", 0.15)
        + s_pos * weights.get("position", 0.15)
        + s_vol * weights.get("volume", 0.25)
        + s_abn * weights.get("abnormal", 0.25)
        + s_rr * weights.get("risk_reward", 0.20)
        + bonus
        - leader_penalty
    )
    total = max(0.0, min(100.0, round(total, 1)))

    verdict = get_verdict(total, s_vol, s_abn, config)
    grade = get_grade(total)

    # ── 红肥绿瘦 + 防S1 过滤器 ──
    timing_cfg = (config or {}).get("timing", {})
    filter_reasons = []
    opens = [r.open for r in rows]
    if timing_cfg.get("volume_pattern_enabled", False):
        vp_ok, vp_ratio = check_volume_pattern(
            closes, volumes, opens, idx,
            window=timing_cfg.get("volume_pattern_window", 50),
            ratio_threshold=timing_cfg.get("volume_pattern_threshold", 0.5),
        )
        if not vp_ok:
            filter_reasons.append(f"红肥绿瘦:{vp_ratio:.2f}")
    if timing_cfg.get("anti_s1_enabled", False):
        s1_ok, _ = check_s1_pattern(
            closes, volumes, opens, idx,
            window=timing_cfg.get("anti_s1_window", 35),
        )
        if not s1_ok:
            filter_reasons.append("放量阴线")
    # ── 过度上涨后第一次回调过滤器 ──
    runaway_cfg = (config or {}).get("excessive_runaway", {})
    if runaway_cfg.get("enabled", True):
        is_excessive, runaway_details = check_excessive_runaway(
            highs, lows, closes, volumes, idx,
            lookback=runaway_cfg.get("lookback_days", 120),
            consecutive_days=runaway_cfg.get("consecutive_days", 4),
            daily_gain_pct=runaway_cfg.get("daily_gain_pct", 7.0),
            short_term_rise_pct=runaway_cfg.get("short_term_rise_pct", 50.0),
            short_term_window=runaway_cfg.get("short_term_window", 20),
            extreme_rise_pct=runaway_cfg.get("extreme_rise_pct", 150.0),
        )
        if is_excessive:
            is_first, _ = check_first_pullback(
                highs, lows, closes, idx,
                runaway_details["peak_idx"],
                min_bounce_pct=runaway_cfg.get("min_bounce_pct", 15.0),
            )
            if is_first:
                reasons_str = "; ".join(runaway_details["hit_reasons"])
                filter_reasons.append(
                    f"过度上涨后第1次回调({reasons_str})"
                )
    if filter_reasons:
        verdict = f"FAIL({', '.join(filter_reasons)})"

    change_pct = (closes[idx] - closes[idx - 1]) / closes[idx - 1] * 100 if idx > 0 else 0

    # 点评
    parts = []
    parts.append("趋势好" if s_trend >= 70 else ("趋势弱" if s_trend < 50 else "趋势一般"))
    parts.append("低位" if position_pct < 40 else ("高位" if position_pct > 70 else "中位"))
    parts.append("量价健康" if s_vol >= 70 else ("量价恶化" if s_vol < 50 else "量价中性"))
    parts.append("主力建仓明显" if s_abn >= 70 else ("无建仓迹象" if s_abn < 40 else "有一定异动"))
    parts.append(f"盈亏比{rr_ratio}:1")

    return RatingResult(
        code=filepath.stem,
        close=closes[idx],
        change_pct=round(change_pct, 2),
        vol_ratio=round(vol_ratio, 2),
        position_pct=round(position_pct, 1),
        trend=s_trend,
        position=s_pos,
        volume=s_vol,
        abnormal=s_abn,
        rr_score=s_rr,
        bonus=bonus,
        total=total,
        grade=grade,
        verdict=verdict,
        signal_type=sig_type,
        signal_name=sig_name,
        stop=stop,
        target=target,
        rr_ratio=rr_ratio,
        comment="，".join(parts),
    )


# ── 批量评分 ──────────────────────────────────────────────


def rate_batch(data_dir: Path, config: Optional[dict] = None) -> List[RatingResult]:
    if config is None:
        config = load_config()
    weights = config.get("weights", DEFAULT_WEIGHTS)

    csv_files = sorted(data_dir.glob("*.csv"))
    csv_files = [f for f in csv_files if not f.name.startswith("rating_report")]

    if not csv_files:
        logger.error("目录下未找到CSV文件: %s", data_dir)
        return []

    logger.info("开始评分 %d 只股票", len(csv_files))

    results: List[RatingResult] = []
    for f in csv_files:
        r = rate_one(f, weights)
        if r:
            results.append(r)

    results.sort(key=lambda x: x.total, reverse=True)

    rank = 1
    for i, r in enumerate(results):
        if i > 0 and r.total < results[i - 1].total:
            rank = i + 1
        r.rank = rank

    return results


# ── 报告输出 ──────────────────────────────────────────────


def generate_reports(results: List[RatingResult], data_dir: Path,
                     weights: dict) -> Tuple[Path, Path]:
    now = datetime.now()
    today_str = now.strftime("%Y%m%d")
    now_str = now.strftime("%Y-%m-%d %H:%M")
    hhmm = now.strftime("%H%M")

    # CSV
    csv_path = data_dir / f"rating_report_{today_str}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "排名", "代码", "收盘价", "涨跌幅%", "量比", "位置%",
            "趋势结构", "价格位置", "量价行为", "前期异动", "盈亏比得分",
            "总分", "评级", "判定", "战法", "信号",
            "止损价", "目标价", "盈亏比", "点评",
        ])
        for r in results:
            chg = f"+{r.change_pct}" if r.change_pct > 0 else f"{r.change_pct}"
            writer.writerow([
                r.rank, r.code, r.close, chg, r.vol_ratio,
                r.position_pct, r.trend, r.position, r.volume,
                r.abnormal, r.rr_score, r.total, r.grade,
                r.verdict, r.signal_type, r.signal_name,
                r.stop, r.target, f"{r.rr_ratio}:1", r.comment,
            ])

    # JSON
    json_path = data_dir / f"rating_report_{today_str}_{hhmm}.json"
    pass_n = sum(1 for r in results if r.verdict == "PASS")
    watch_n = sum(1 for r in results if r.verdict == "WATCH")
    fail_n = sum(1 for r in results if r.verdict == "FAIL")
    b1_n = sum(1 for r in results if r.signal_type == "B1")
    b2_n = sum(1 for r in results if r.signal_type == "B2")
    other_n = sum(1 for r in results if r.signal_type == "其他")

    json_data = {
        "generate_time": now_str,
        "weights": weights,
        "total": len(results),
        "summary": {
            "pass": pass_n, "watch": watch_n, "fail": fail_n,
            "b1": b1_n, "b2": b2_n, "other": other_n,
        },
        "results": [{
            "rank": r.rank, "code": r.code, "close": r.close,
            "change_pct": r.change_pct, "vol_ratio": r.vol_ratio,
            "position_pct": r.position_pct,
            "scores": {
                "trend": r.trend, "position": r.position,
                "volume": r.volume, "abnormal": r.abnormal,
                "risk_reward": r.rr_score, "bonus": r.bonus,
            },
            "total": r.total, "grade": r.grade, "verdict": r.verdict,
            "signal_type": r.signal_type, "signal_name": r.signal_name,
            "stop": r.stop, "target": r.target,
            "risk_reward_ratio": r.rr_ratio, "comment": r.comment,
        } for r in results],
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    return csv_path, json_path


def print_summary(results: List[RatingResult]) -> None:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    pass_n = sum(1 for r in results if r.verdict == "PASS")
    watch_n = sum(1 for r in results if r.verdict == "WATCH")
    fail_n = sum(1 for r in results if r.verdict == "FAIL")
    b1_n = sum(1 for r in results if r.signal_type == "B1")
    b2_n = sum(1 for r in results if r.signal_type == "B2")
    other_n = sum(1 for r in results if r.signal_type == "其他")

    print(f"\n{'=' * 90}")
    print(f"Z哥战法评分报告 | {now_str} | 共{len(results)}只")
    print(f"判定: PASS={pass_n}  WATCH={watch_n}  FAIL={fail_n}")
    print(f"战法: B1={b1_n}  B2={b2_n}  其他={other_n}")
    print(f"{'=' * 90}")
    print(
        f"{'排名':>4} {'代码':>8} {'收盘':>8} {'涨幅%':>7} "
        f"{'总分':>6} {'评级':>4} {'判定':>6} {'战法':>4} {'信号':>8} {'盈亏比':>7}"
    )
    print("-" * 90)

    for r in results:
        chg = f"+{r.change_pct}" if r.change_pct > 0 else f"{r.change_pct}"
        print(
            f"{r.rank:>4} {r.code:>8} {r.close:>8.2f} {chg:>7} "
            f"{r.total:>6.1f} {r.grade:>4} {r.verdict:>6} {r.signal_type:>4} "
            f"{r.signal_name:>8} {r.rr_ratio}:1"
        )


# ── CLI入口 ──────────────────────────────────────────────


def run_rating(path: Path, config_path: Path = None) -> Optional[List[RatingResult]]:
    """CLI 入口兼容函数。"""
    if config_path is None:
        config = load_config()
    else:
        config = load_config(config_path)
    weights = config.get("weights", DEFAULT_WEIGHTS)

    if path.is_file():
        result = rate_one(path, weights)
        if result is None:
            print("评分失败：数据不足")
            return None
        results = [result]
        data_dir = path.parent
    elif path.is_dir():
        results = rate_batch(path, config)
        data_dir = path
    else:
        print(f"路径不存在: {path}")
        return None

    if not results:
        print("无评分结果")
        return None

    print_summary(results)
    csv_path, json_path = generate_reports(results, data_dir, weights)
    print(f"\nCSV报告已保存: {csv_path}")
    print(f"JSON报告已保存: {json_path}")
    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Z哥战法股票批量评分")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(_PROJECT_ROOT / "data" / "raw"),
        help="CSV文件或目录路径（默认: data/raw/）",
    )
    parser.add_argument(
        "-c", "--config",
        default=str(_CONFIG_PATH),
        help="配置文件路径",
    )
    args = parser.parse_args()

    result = run_rating(Path(args.path), Path(args.config) if args.config else None)
    if result is None:
        sys.exit(1)


if __name__ == "__main__":
    main()


# ── FastAPI 集成函数 ───────────────────────────────────────────

def rate_stocks_with_klines(stocks_data: List[dict], config: Optional[dict] = None) -> List[RatingResult]:
    """
    评分多只股票（FastAPI 调用入口）

    将内存中的 K-line 数据写入临时 CSV 文件，复用 rate_one() 评分逻辑。
    """
    import tempfile
    import os

    if config is None:
        config = load_config()
    weights = config.get("weights", DEFAULT_WEIGHTS)

    # Pre-fetch industry data
    codes = [s["code"] for s in stocks_data]
    try:
        from scoring.industry import prefetch_industries
        industry_map = prefetch_industries(codes)
    except Exception:
        industry_map = {code: {"industry": "未知", "sub_industry": ""} for code in codes}

    # Build name lookup
    name_map = {s["code"]: s.get("name", "") for s in stocks_data}

    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for stock in stocks_data:
            code = stock["code"]
            klines = stock["klines"]

            if len(klines) < 20:
                logger.warning(f"{code} 数据不足20条，跳过")
                continue

            # Write K-lines to temp CSV
            csv_path = os.path.join(tmpdir, f"{code}.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "open", "close", "high", "low", "volume"])
                for k in klines:
                    writer.writerow([k.date, k.open, k.close, k.high, k.low, k.volume])

            try:
                result = rate_one(Path(csv_path), weights)
                if result:
                    result.code = code
                    ind = industry_map.get(code, {"industry": "未知", "sub_industry": ""})
                    result.industry = ind["industry"]
                    result.sub_industry = ind["sub_industry"]
                    results.append(result)
            except Exception as e:
                logger.error(f"评分 {code} 失败: {e}")
                continue

    # Sort and assign ranks
    results.sort(key=lambda x: x.total, reverse=True)
    rank = 1
    for i, r in enumerate(results):
        if i > 0 and r.total < results[i - 1].total:
            rank = i + 1
        r.rank = rank

    return results
