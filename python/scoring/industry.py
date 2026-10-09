# -*- coding: utf-8 -*-
"""
股票行业信息获取模块
基于 Tushare Pro API，支持本地缓存
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("industry")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CACHE_PATH = _PROJECT_ROOT / "data" / "industry_cache.json"

_cache: Dict[str, Dict[str, str]] = {}
_cache_loaded = False
_tushare_failed = False


def _to_ts_code(code: str) -> str:
    """6 位代码 → tushare 格式：600000.SH"""
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    elif code.startswith(("4", "8")):
        return f"{code}.BJ"
    else:
        return f"{code}.SZ"


def _load_cache() -> None:
    """从本地文件加载缓存"""
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    _cache_loaded = True

    if _CACHE_PATH.exists():
        try:
            data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            _cache = {k: v for k, v in data.items() if not k.startswith("_")}
            logger.debug("已加载行业缓存，共 %d 只股票", len(_cache))
        except Exception as e:
            logger.warning("行业缓存文件读取失败: %s", e)
            _cache = {}
    else:
        _cache = {}


def _save_cache() -> None:
    """保存缓存到本地文件"""
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "_meta": {
            "updated_at": datetime.now().isoformat(),
            "count": len(_cache),
            "tushare_available": not _tushare_failed,
        },
    }
    data.update(_cache)
    _CACHE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.debug("已保存行业缓存，共 %d 只股票", len(_cache))


def _fetch_from_tushare(codes: list[str]) -> Dict[str, Dict[str, str]]:
    """调用 Tushare API 获取行业信息

    Returns:
        {code: {"industry": str, "sub_industry": str}}
    """
    global _tushare_failed
    if _tushare_failed:
        return {}

    try:
        import tushare as ts
        import yaml

        cfg_path = _PROJECT_ROOT / "config" / "fetch_kline.yaml"
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                fetch_cfg = yaml.safe_load(f) or {}
            token = fetch_cfg.get("tushare", {}).get("token")
        else:
            token = None
        if not token:
            logger.warning("tushare token 未配置，行业数据不可用")
            _tushare_failed = True
            return {}

        os.environ["NO_PROXY"] = "api.waditu.com,.waditu.com,waditu.com"
        os.environ["no_proxy"] = os.environ["NO_PROXY"]
        ts.set_token(token)
        pro = ts.pro_api()

        df = pro.stock_basic(
            exchange="", list_status="L", fields="ts_code,symbol,industry"
        )
        if df is None or df.empty:
            logger.warning("tushare stock_basic 返回空数据")
            _tushare_failed = True
            return {}

        result = {}
        for _, row in df.iterrows():
            code = str(row.get("symbol", "")).zfill(6)
            industry = str(row.get("industry", "")).strip() or "未知"
            result[code] = {"industry": industry, "sub_industry": ""}

        logger.info("从 tushare 获取行业数据，共 %d 只股票", len(result))
        return result

    except ImportError:
        logger.warning("tushare 包未安装，行业数据不可用")
        _tushare_failed = True
        return {}
    except Exception as e:
        logger.warning("tushare 行业数据获取失败: %s", e)
        _tushare_failed = True
        return {}


def prefetch_industries(codes: list[str]) -> Dict[str, Dict[str, str]]:
    """批量预取行业信息

    Args:
        codes: 6位股票代码列表

    Returns:
        {code: {"industry": str, "sub_industry": str}}
    """
    _load_cache()

    missing = [c for c in codes if c not in _cache]
    if missing and not _tushare_failed:
        new_data = _fetch_from_tushare(missing)
        if new_data:
            _cache.update(new_data)
            _save_cache()
        # 缓存 tushare 未返回的代码（已退市等）
        for c in missing:
            if c not in _cache:
                _cache[c] = {"industry": "未知", "sub_industry": ""}
        if new_data:
            _save_cache()

    return {
        c: _cache.get(c, {"industry": "未知", "sub_industry": ""}) for c in codes
    }


def get_industry(code: str) -> Dict[str, str]:
    """获取单只股票的行业信息

    Args:
        code: 6位股票代码

    Returns:
        {"industry": str, "sub_industry": str}
    """
    result = prefetch_industries([code])
    return result.get(code, {"industry": "未知", "sub_industry": ""})
