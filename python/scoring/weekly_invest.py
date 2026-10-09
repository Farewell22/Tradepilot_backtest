# -*- coding: utf-8 -*-
"""
周线定投分析模块

复用 ref/pipeline/weekly_invest.py 的核心计算逻辑，
通过 FastAPI 端点供 Go 后端调用。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from scoring.stock_rater import calc_kdj, calc_ma, KLineRow
from scoring.brick_indicator import compute_zx_lines

logger = logging.getLogger(__name__)


def daily_to_weekly(daily_rows: List[KLineRow]) -> List[KLineRow]:
    """将日线 KLineRow 列表聚合为周线。按 ISO 周分组。"""
    if not daily_rows:
        return []
    from datetime import datetime, timedelta
    import copy

    def _get_week_key(date_str: str) -> str:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    weeks: list[dict] = []
    current_week_key = None
    current_week = None

    for row in daily_rows:
        wk = _get_week_key(row.date)
        if wk != current_week_key:
            if current_week is not None:
                weeks.append(current_week)
            current_week_key = wk
            current_week = {
                "date": row.date,
                "open": row.open,
                "close": row.close,
                "high": row.high,
                "low": row.low,
                "volume": row.volume,
            }
        else:
            current_week["date"] = row.date
            current_week["close"] = row.close
            current_week["high"] = max(current_week["high"], row.high)
            current_week["low"] = min(current_week["low"], row.low)
            current_week["volume"] += row.volume

    if current_week is not None:
        weeks.append(current_week)

    return [KLineRow(**w) for w in weeks]

# 默认配置（与 ref/config/weekly_invest.yaml 一致）
DEFAULT_CONFIG = {
    "fetch": {
        "start": "20240101",
        "end": "today",
    },
    "thresholds": {
        "weekly_j": 0.0,
        "daily_j": 0.0,
        "use_percentile": False,
        "percentile_threshold": 5.0,
    },
    "bull_bear": {
        "enabled": True,
        "ma27_period": 27,
        "ma47_period": 47,
        "min_weeks": 50,
    },
    "yellow_white": {
        "enabled": True,
        "zxdq_span": 10,
        "zxdkx_m1": 14,
        "zxdkx_m2": 28,
        "zxdkx_m3": 57,
        "zxdkx_m4": 114,
    },
}


@dataclass
class WIResult:
    """单只标的的分析结果"""
    code: str
    name: str
    close_price: float
    weekly_j: float
    daily_j: float
    alert_level: str
    kdj_alert_level: str
    weekly_j_percentile: Optional[float]
    daily_j_percentile: Optional[float]
    ma27_value: Optional[float]
    ma47_value: Optional[float]
    bull_bear_signal: Optional[str]
    bull_bear_desc: str
    zxdq_value: Optional[float]
    zxdkx_value: Optional[float]
    yellow_white_status: str


def _merge_config(config: Optional[dict]) -> dict:
    """合并用户配置与默认配置"""
    if config is None:
        return DEFAULT_CONFIG.copy()
    merged = DEFAULT_CONFIG.copy()
    for key in config:
        if key in merged and isinstance(merged[key], dict) and isinstance(config[key], dict):
            merged[key] = {**merged[key], **config[key]}
        else:
            merged[key] = config[key]
    return merged


def _calc_j_percentile(j_vals: List[float], current_j: float) -> Optional[float]:
    """计算当前J值在历史J值中的分位排名"""
    if len(j_vals) < 20:
        return None
    rank = sum(1 for v in j_vals if v <= current_j)
    return round(rank / len(j_vals) * 100, 1)


def _calc_bull_bear_signal(weekly_rows: List[KLineRow], config: dict) -> dict:
    """基于周线 MA27/MA47 检测牛熊转换信号"""
    bb_cfg = config.get("bull_bear", {})
    if not bb_cfg.get("enabled", False):
        return {"ma27_value": None, "ma47_value": None,
                "bull_bear_signal": None, "bull_bear_desc": ""}

    ma27_period = bb_cfg.get("ma27_period", 27)
    ma47_period = bb_cfg.get("ma47_period", 47)
    min_weeks = bb_cfg.get("min_weeks", 50)

    if len(weekly_rows) < min_weeks:
        return {"ma27_value": None, "ma47_value": None,
                "bull_bear_signal": None, "bull_bear_desc": ""}

    w_closes = [r.close for r in weekly_rows]
    ma27_vals = calc_ma(w_closes, ma27_period)
    ma47_vals = calc_ma(w_closes, ma47_period)

    idx = len(weekly_rows) - 1
    ma27_now = ma27_vals[idx]
    ma47_now = ma47_vals[idx]
    ma27_prev = ma27_vals[idx - 1]
    ma47_prev = ma47_vals[idx - 1]

    current_close = w_closes[idx]
    prev_close = w_closes[idx - 1]

    signal = None
    desc = ""

    # 熊转牛（蓝色）：前一根收盘 <= MA47，当前收盘 > MA47
    if (ma47_prev is not None and ma47_now is not None
            and prev_close <= ma47_prev
            and current_close > ma47_now):
        signal = "bear_to_bull"
        desc = f"收盘{current_close:.2f}上穿MA47({ma47_now:.2f})"

    # 牛转熊（紫色）：前一根收盘 >= MA27，当前收盘 < MA27
    elif (ma27_prev is not None and ma27_now is not None
            and prev_close >= ma27_prev
            and current_close < ma27_now):
        signal = "bull_to_bear"
        desc = f"收盘{current_close:.2f}下穿MA27({ma27_now:.2f})"

    return {
        "ma27_value": round(ma27_now, 2) if ma27_now is not None else None,
        "ma47_value": round(ma47_now, 2) if ma47_now is not None else None,
        "bull_bear_signal": signal,
        "bull_bear_desc": desc,
    }


def analyze_single(code: str, klines: List[dict], config: dict,
                   name: str = "") -> Optional[WIResult]:
    """分析单只标的的周线定投信号

    Args:
        code: 标的代码
        klines: K线数据列表，每条包含 date,open,close,high,low,volume
        config: 配置字典
        name: 标的名称

    Returns:
        WIResult 或 None（数据不足时）
    """
    if not klines or len(klines) < 9:
        logger.debug("%s 数据不足（需>=9根K线，实际%d），跳过",
                     code, len(klines) if klines else 0)
        return None

    # 转换为 KLineRow
    rows = []
    for k in klines:
        rows.append(KLineRow(
            date=str(k["date"])[:10],
            open=float(k["open"]),
            close=float(k["close"]),
            high=float(k["high"]),
            low=float(k["low"]),
            volume=float(k.get("volume", 0)),
        ))

    # 日线 KDJ
    daily_highs = [r.high for r in rows]
    daily_lows = [r.low for r in rows]
    daily_closes = [r.close for r in rows]
    _, _, daily_j_vals = calc_kdj(daily_highs, daily_lows, daily_closes)
    current_daily_j = daily_j_vals[-1]

    # 周线 KDJ
    weekly_rows = daily_to_weekly(rows)
    if len(weekly_rows) < 9:
        logger.debug("%s 周线数据不足（需>=9根，实际%d），仅使用日线",
                     code, len(weekly_rows))
        current_weekly_j = 50.0
        weekly_j_percentile = None
    else:
        w_highs = [r.high for r in weekly_rows]
        w_lows = [r.low for r in weekly_rows]
        w_closes = [r.close for r in weekly_rows]
        _, _, weekly_j_vals = calc_kdj(w_highs, w_lows, w_closes)
        current_weekly_j = weekly_j_vals[-1]
        weekly_j_percentile = _calc_j_percentile(weekly_j_vals, current_weekly_j)

    # 日线分位
    daily_j_percentile = _calc_j_percentile(daily_j_vals, current_daily_j)

    # 牛熊转换检测
    bb_result = _calc_bull_bear_signal(weekly_rows, config)

    # 黄白线计算
    yw_cfg = config.get("yellow_white", {})
    yw_enabled = yw_cfg.get("enabled", True)

    zxdq_value = None
    zxdkx_value = None
    yellow_white_status = ""

    if yw_enabled and len(rows) >= 114:
        df_kline = pd.DataFrame([{
            "close": r.close,
            "open": r.open,
            "high": r.high,
            "low": r.low,
        } for r in rows])
        zxdq, zxdkx = compute_zx_lines(
            df_kline,
            m1=yw_cfg.get("zxdkx_m1", 14),
            m2=yw_cfg.get("zxdkx_m2", 28),
            m3=yw_cfg.get("zxdkx_m3", 57),
            m4=yw_cfg.get("zxdkx_m4", 114),
            zxdq_span=yw_cfg.get("zxdq_span", 10),
        )
        current_zxdq = zxdq.iloc[-1]
        current_zxdkx = zxdkx.iloc[-1]
        zxdq_value = round(float(current_zxdq), 2)
        zxdkx_value = round(float(current_zxdkx), 2)
        yellow_white_status = "above" if current_zxdq > current_zxdkx else "below"

    # KDJ 阈值判定
    thresholds = config.get("thresholds", {})
    weekly_j_threshold = thresholds.get("weekly_j", 0)
    daily_j_threshold = thresholds.get("daily_j", 0)
    use_percentile = thresholds.get("use_percentile", False)
    percentile_threshold = thresholds.get("percentile_threshold", 5)

    weekly_triggered = current_weekly_j < weekly_j_threshold
    daily_triggered = current_daily_j < daily_j_threshold

    if use_percentile:
        if weekly_j_percentile is not None and weekly_j_percentile < percentile_threshold:
            weekly_triggered = True
        if daily_j_percentile is not None and daily_j_percentile < percentile_threshold:
            daily_triggered = True

    if weekly_triggered and daily_triggered:
        kdj_alert_level = "orange"
    elif weekly_triggered:
        kdj_alert_level = "yellow"
    else:
        kdj_alert_level = "none"

    # 黄白线修正：白线<黄线时标记为grey
    if yellow_white_status == "below":
        if kdj_alert_level in ("orange", "yellow", "none"):
            kdj_alert_level = "grey"

    # 牛熊信号优先级高于 KDJ 告警
    bb_signal = bb_result.get("bull_bear_signal")
    if bb_signal == "bear_to_bull":
        alert_level = "blue"
    elif bb_signal == "bull_to_bear":
        alert_level = "purple"
    else:
        alert_level = kdj_alert_level

    return WIResult(
        code=code,
        name=name,
        close_price=round(rows[-1].close, 2),
        weekly_j=round(current_weekly_j, 2),
        daily_j=round(current_daily_j, 2),
        alert_level=alert_level,
        kdj_alert_level=kdj_alert_level,
        weekly_j_percentile=weekly_j_percentile,
        daily_j_percentile=daily_j_percentile,
        ma27_value=bb_result.get("ma27_value"),
        ma47_value=bb_result.get("ma47_value"),
        bull_bear_signal=bb_result.get("bull_bear_signal"),
        bull_bear_desc=bb_result.get("bull_bear_desc", ""),
        zxdq_value=zxdq_value,
        zxdkx_value=zxdkx_value,
        yellow_white_status=yellow_white_status,
    )


def analyze_batch(stocks: List[dict], kline_map: dict,
                  config: Optional[dict] = None) -> List[dict]:
    """批量分析多只标的

    Args:
        stocks: 标的列表，每项包含 code, name
        kline_map: K线数据映射 {code: [kline_dict, ...]}
        config: 可选配置

    Returns:
        结果列表（dict格式，可直接JSON序列化）
    """
    merged_config = _merge_config(config)
    results = []

    for stock in stocks:
        code = stock["code"]
        name = stock.get("name", "")
        klines = kline_map.get(code, [])

        if not klines:
            logger.warning("无K线数据: %s", code)
            continue

        try:
            result = analyze_single(code, klines, merged_config, name)
            if result is not None:
                results.append({
                    "code": result.code,
                    "name": result.name,
                    "close_price": result.close_price,
                    "weekly_j": result.weekly_j,
                    "daily_j": result.daily_j,
                    "alert_level": result.alert_level,
                    "kdj_alert_level": result.kdj_alert_level,
                    "weekly_j_percentile": result.weekly_j_percentile,
                    "daily_j_percentile": result.daily_j_percentile,
                    "ma27_value": result.ma27_value,
                    "ma47_value": result.ma47_value,
                    "bull_bear_signal": result.bull_bear_signal,
                    "bull_bear_desc": result.bull_bear_desc,
                    "zxdq_value": result.zxdq_value,
                    "zxdkx_value": result.zxdkx_value,
                    "yellow_white_status": result.yellow_white_status,
                })
        except Exception as e:
            logger.error("分析 %s 失败: %s", code, e)

    return results
