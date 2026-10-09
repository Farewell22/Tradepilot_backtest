# -*- coding: utf-8 -*-
"""
数据源抽象层
支持 tushare 和腾讯财经两种 K 线数据源，通过工厂函数创建。
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd
import requests
from datetime import datetime, date

logger = logging.getLogger("data_source")


# --------------------------- 交易日判断工具 --------------------------- #
# BUG-00020: A股休市日列表（按年度维护，每年更新）

_HOLIDAYS_2025 = frozenset({
    # 元旦
    "2025-01-01",
    # 春节
    "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31",
    "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",
    # 清明节
    "2025-04-04", "2025-04-05", "2025-04-06",
    # 劳动节
    "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",
    # 端午节
    "2025-05-31", "2025-06-01", "2025-06-02",
    # 中秋节 + 国庆节
    "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04",
    "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
})

_HOLIDAYS_2026 = frozenset({
    # 元旦
    "2026-01-01", "2026-01-02", "2026-01-03",
    # 春节
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20", "2026-02-21", "2026-02-22",
    # 清明节
    "2026-04-04", "2026-04-05", "2026-04-06",
    # 劳动节
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    # 端午节
    "2026-05-30", "2026-05-31", "2026-06-01",
    # 国庆节
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
})

_ALL_HOLIDAYS = _HOLIDAYS_2025 | _HOLIDAYS_2026


def is_trading_day(dt: datetime | date | None = None) -> bool:
    """检查给定日期是否为中国A股交易日（简单启发式）。

    使用周末检查 + 可配置的中国节假日列表。
    并非详尽无遗——覆盖了主要的法定节假日。
    可通过 config/fetch_kline.yaml 中的 trading_holidays 进行扩展。

    Args:
        dt: 要检查的日期，默认为今天

    Returns:
        如果可能是交易日则为 True，如果肯定是休市日则为 False
    """
    if dt is None:
        dt = date.today()
    elif isinstance(dt, pd.Timestamp):
        dt = dt.date()
    elif isinstance(dt, datetime):
        dt = dt.date()

    # 1. 排除周末
    if dt.weekday() >= 5:  # 5=周六, 6=周日
        return False

    # 2. 格式化为字符串用于节假日查找
    date_str = dt.strftime("%Y-%m-%d")

    # 3. 优先从配置文件读取节假日列表
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "fetch_kline.yaml"
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            config_holidays = cfg.get("trading_holidays", [])
            if config_holidays and date_str in config_holidays:
                return False
    except Exception:
        pass  # 配置读取失败时继续使用硬编码列表

    # 4. 检查硬编码节假日列表
    if date_str in _ALL_HOLIDAYS:
        return False

    return True


def is_in_trading_hours() -> bool:
    """判断当前是否在 A 股交易时段（9:30-11:30, 13:00-15:00）"""
    now = datetime.now()
    # 先检查是否为交易日
    if not is_trading_day(now.date()):
        return False
    h, m = now.hour, now.minute
    # 上午 9:30-11:30
    if (h == 9 and m >= 30) or h == 10 or (h == 11 and m <= 30):
        return True
    # 下午 13:00-15:00
    if 13 <= h < 15:
        return True
    return False


# --------------------------- 代码格式转换工具 --------------------------- #

def _parse_qt_realtime(qt_data: dict | list, date_str: str) -> dict | None:
    """从腾讯 API 响应的 qt 字段解析实时报价数据。

    Args:
        qt_data: qt 字段内容，格式为 {market_code: [...]} 或 [...]
        date_str: 日期字符串 YYYY-MM-DD

    Returns:
        包含 date, open, close, high, low, volume 的字典，解析失败返回 None
    """
    try:
        # qt_data 可能是 {market_code: [...]} 格式
        if isinstance(qt_data, dict):
            values = list(qt_data.values())
            if not values:
                return None
            qt_list = values[0]
        elif isinstance(qt_data, list):
            qt_list = qt_data
        else:
            return None

        if not isinstance(qt_list, list) or len(qt_list) < 7:
            return None

        # qt_list 常见格式: [..., 代码, 名称, 当前价, 昨收, 今开, 成交量, ...]
        # 索引 3=当前价, 4=昨收, 5=今开, 6=成交量
        current_price = float(qt_list[3]) if qt_list[3] else 0.0
        open_price = float(qt_list[5]) if qt_list[5] else current_price
        volume = float(qt_list[6]) if qt_list[6] else 0.0

        if current_price <= 0:
            return None

        # high/low 无法从 qt 获取，用保守估计
        high = max(open_price, current_price)
        low = min(open_price, current_price)

        return {
            "date": date_str,
            "open": open_price,
            "close": current_price,
            "high": high,
            "low": low,
            "volume": volume,
        }
    except (ValueError, TypeError, IndexError) as e:
        logger.debug("解析 qt 实时报价失败: %s, qt_data=%s", e, qt_data)
        return None


def _to_ts_code(code: str) -> str:
    """6 位代码 → tushare 格式：600000.SH"""
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    elif code.startswith(("4", "8")):
        return f"{code}.BJ"
    else:
        return f"{code}.SZ"


def _to_tencent_code(code: str) -> str:
    """6 位代码 → 腾讯格式：sh600000"""
    code = str(code).zfill(6)
    if code.startswith(("5", "60", "68", "9")):
        return f"sh{code}"
    elif code.startswith(("4", "8")):
        return f"bj{code}"
    else:
        return f"sz{code}"


# --------------------------- 抽象基类 --------------------------- #

class KLineSource(ABC):
    """K 线数据源抽象基类"""

    @abstractmethod
    def initialize(self, config: dict) -> None:
        """初始化数据源（设置 token、session 等）"""

    @abstractmethod
    def fetch_kline(self, code: str, start: str, end: str) -> pd.DataFrame:
        """
        获取单只股票的 K 线数据。

        Args:
            code: 6 位股票代码
            start: 开始日期 YYYYMMDD
            end: 结束日期 YYYYMMDD

        Returns:
            DataFrame，列为 date, open, close, high, low, volume
            date 为 pd.Timestamp，无数据时返回空 DataFrame
        """

    def fetch_kline_after(self, code: str, start_date: str) -> pd.DataFrame:
        """获取从 start_date 到今天的日 K 线数据。

        Args:
            code: 6 位股票代码
            start_date: 开始日期 YYYY-MM-DD

        Returns:
            DataFrame，列为 date, open, close, high, low, volume
        """
        start_compact = start_date.replace("-", "")
        end_compact = datetime.now().strftime("%Y%m%d")
        return self.fetch_kline(code, start_compact, end_compact)


# --------------------------- Tushare 实现 --------------------------- #

class TushareSource(KLineSource):
    """基于 tushare pro 的数据源"""

    def __init__(self):
        self.pro = None

    def initialize(self, config: dict) -> None:
        import tushare as ts

        tushare_cfg = config.get("tushare", {})
        ts_token = tushare_cfg.get("token")

        if not ts_token:
            raise ValueError(
                "Tushare token 未配置。请在 fetch_kline.yaml 的 tushare.token 中设置"
            )

        os.environ["NO_PROXY"] = "api.waditu.com,.waditu.com,waditu.com"
        os.environ["no_proxy"] = os.environ["NO_PROXY"]

        ts.set_token(ts_token)
        self.pro = ts.pro_api()
        logger.info("Tushare 数据源已初始化")

    def fetch_kline(self, code: str, start: str, end: str) -> pd.DataFrame:
        import tushare as ts

        ts_code = _to_ts_code(code)
        try:
            df = ts.pro_bar(
                ts_code=ts_code,
                adj="qfq",
                start_date=start,
                end_date=end,
                freq="D",
                api=self.pro,
            )
        except Exception as e:
            raise

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns={"trade_date": "date", "vol": "volume"})[
            ["date", "open", "close", "high", "low", "volume"]
        ].copy()

        df["date"] = pd.to_datetime(df["date"])
        for c in ["open", "close", "high", "low", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        return df.sort_values("date").reset_index(drop=True)


# --------------------------- 腾讯财经实现 --------------------------- #

class TencentSource(KLineSource):
    """基于腾讯财经历史 K 线 API 的数据源"""

    HISTORICAL_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    REALTIME_QUOTE_URL = "https://qt.gtimg.cn/q="

    def __init__(self):
        self.session = None
        self.rate_limit_delay = 0.5
        self.max_retries = 3

    def initialize(self, config: dict) -> None:
        tencent_cfg = config.get("tencent", {})
        self.rate_limit_delay = tencent_cfg.get("rate_limit_delay", 0.5)
        self.max_retries = tencent_cfg.get("max_retries", 3)
        self.session = requests.Session()
        logger.info("腾讯财经数据源已初始化")

    def fetch_realtime_quote(self, code: str) -> dict | None:
        """独立获取实时报价（作为 qt 字段缺失时的备用方案）。

        腾讯实时行情 API: https://qt.gtimg.cn/q={market_code}
        响应格式: v_sh600519="1~名称~代码~当前价~昨收~今开~成交量~...~最高~最低~..."

        Args:
            code: 6 位股票代码（如 "600519"）

        Returns:
            {current_price, prev_close, open, volume, high, low} 或 None
        """
        market_code = _to_tencent_code(code)
        try:
            resp = self.session.get(f"{self.REALTIME_QUOTE_URL}{market_code}", timeout=5)
            resp.raise_for_status()
            parts = resp.text.split("~")
            if len(parts) < 36:
                return None

            current_price = float(parts[3]) if parts[3] else 0.0
            if current_price <= 0:
                return None

            return {
                "current_price": current_price,
                "prev_close": float(parts[4]) if parts[4] else 0.0,
                "open": float(parts[5]) if parts[5] else current_price,
                "volume": float(parts[6]) if parts[6] else 0.0,
                "high": float(parts[33]) if parts[33] else 0.0,
                "low": float(parts[34]) if parts[34] else 0.0,
            }
        except Exception as e:
            logger.debug("获取 %s 实时报价失败: %s", code, e)
            return None

    def fetch_kline(self, code: str, start: str, end: str) -> pd.DataFrame:
        """获取股票K线数据（自动转换6位代码为市场代码）。"""
        market_code = _to_tencent_code(code)
        return self._do_fetch_kline(market_code, start, end)

    def fetch_kline_raw(self, market_code: str, start: str, end: str) -> pd.DataFrame:
        """使用原始市场代码获取K线数据（用于指数等特殊代码）。

        Args:
            market_code: 原始市场代码，如 "sh000001"（上证指数）、"sz399001"（深证成指）、"us.DJI"（道琼斯）
            start: 开始日期 YYYYMMDD
            end: 结束日期 YYYYMMDD

        Returns:
            DataFrame，列为 date, open, close, high, low, volume
        """
        return self._do_fetch_kline(market_code, start, end)

    def _do_fetch_kline(self, market_code: str, start: str, end: str) -> pd.DataFrame:
        """内部方法：执行K线数据获取和解析。"""
        # 格式化日期为 YYYY-MM-DD（兼容 YYYYMMDD 和 YYYY-MM-DD 输入）
        if len(start) == 10 and '-' in start:
            start_fmt = start
        else:
            start_fmt = f"{start[:4]}-{start[4:6]}-{start[6:8]}"
        if len(end) == 10 and '-' in end:
            end_fmt = end
        else:
            end_fmt = f"{end[:4]}-{end[4:6]}-{end[6:8]}"

        params = {
            "param": f"{market_code},day,{start_fmt},{end_fmt},300,qfq",
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(self.HISTORICAL_KLINE_URL, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                if attempt == self.max_retries:
                    logger.warning("腾讯API获取 %s 失败(%d次): %s", market_code, attempt, e)
                    return pd.DataFrame()
                time.sleep(self.rate_limit_delay * attempt)

        # 解析 JSON 响应
        # data 结构: {"code": 0, "msg": "", "data": {"sh600000": {"day": [...], "qt": {...}}}}
        data_dict = data.get("data", {})
        if not data_dict:
            return pd.DataFrame()

        # 取第一个 key 对应的数据
        stock_data = list(data_dict.values())[0]
        # qfqday 是前复权日K，day 是不复权（指数无qfqday，使用day）
        kline_list = stock_data.get("qfqday") or stock_data.get("day") or []

        if not kline_list:
            return pd.DataFrame()

        # 每条记录: ["YYYY-MM-DD", open, close, high, low, volume]
        rows = []
        for item in kline_list:
            if len(item) >= 6:
                rows.append({
                    "date": item[0],
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]),
                })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        for c in ["open", "close", "high", "low", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        # --- 实时报价覆盖 ---
        if not df.empty:
            requested_end = pd.to_datetime(end_fmt)
            last_date = pd.to_datetime(df.iloc[-1]["date"]).normalize()
            requested_end_normalized = requested_end.normalize()

            qt_data = stock_data.get("qt", {})
            is_trading = is_trading_day(requested_end_normalized.date())

            # 优先从 qt 字段获取实时数据
            realtime_info = _parse_qt_realtime(qt_data, end_fmt) if qt_data else None

            # 备用方案：盘中 qt 缺失时，独立获取实时报价
            if realtime_info is None and is_trading and is_in_trading_hours():
                # 仅处理 A 股代码（sh/sz/bj 前缀）
                code_6digit = market_code[2:] if market_code[:2] in ("sh", "sz", "bj") else None
                if code_6digit:
                    logger.debug("qt 字段缺失，独立获取 %s 实时报价", market_code)
                    rt = self.fetch_realtime_quote(code_6digit)
                    if rt and rt["current_price"] > 0:
                        realtime_info = {
                            "date": end_fmt,
                            "open": rt["open"],
                            "close": rt["current_price"],
                            "high": rt["high"] or max(rt["open"], rt["current_price"]),
                            "low": rt["low"] or min(rt["open"], rt["current_price"]),
                            "volume": rt["volume"],
                        }

            # 覆盖逻辑（与原有逻辑一致）
            if realtime_info:
                if last_date == requested_end_normalized:
                    # 最后一条是请求的结束日期，用实时价格更新（盘中获取最新价）
                    old_close = df.iloc[-1]["close"]
                    df.iloc[-1, df.columns.get_loc("close")] = realtime_info["close"]
                    df.iloc[-1, df.columns.get_loc("high")] = max(
                        df.iloc[-1]["high"], realtime_info["close"]
                    )
                    df.iloc[-1, df.columns.get_loc("low")] = min(
                        df.iloc[-1]["low"], realtime_info["close"]
                    )
                    logger.debug(
                        "已更新 %s 实时报价: %.2f -> %.2f",
                        market_code, old_close, realtime_info["close"]
                    )
                elif last_date < requested_end_normalized:
                    if is_trading and is_in_trading_hours():
                        # 交易时段内：最后一条早于结束日期，补充当日新行
                        realtime_info["date"] = pd.to_datetime(realtime_info["date"])
                        df = pd.concat([df, pd.DataFrame([realtime_info])], ignore_index=True)
                        logger.info("已补充 %s 盘中实时报价: %.2f", market_code, realtime_info["close"])
                    else:
                        # 非交易日：用最新报价更新最后一条（避免伪造非交易日K线）
                        old_close = df.iloc[-1]["close"]
                        df.iloc[-1, df.columns.get_loc("close")] = realtime_info["close"]
                        df.iloc[-1, df.columns.get_loc("high")] = max(
                            df.iloc[-1]["high"], realtime_info["close"]
                        )
                        df.iloc[-1, df.columns.get_loc("low")] = min(
                            df.iloc[-1]["low"], realtime_info["close"]
                        )
                        logger.debug(
                            "已更新 %s 最新报价(非交易): %.2f -> %.2f",
                            market_code, old_close, realtime_info["close"]
                        )

        return df.sort_values("date").reset_index(drop=True)


class TencentMinuteSource:
    """腾讯分钟级 K 线数据源（支持 1m/5m/15m/30m/60m）"""

    MINUTE_KLINE_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"

    def __init__(self):
        self.session = requests.Session()
        self.rate_limit_delay = 0.5

    def fetch_minute_kline_range(
        self, code: str, start: str, end: str, frequency: str = "5m",
    ) -> pd.DataFrame:
        """Fetch a closed date range by paging backward from Tencent's minute endpoint."""
        start_date = pd.Timestamp(start).normalize()
        end_date = pd.Timestamp(end).normalize()
        if start_date > end_date:
            raise ValueError("分钟线开始日期晚于结束日期")
        market_code = _to_tencent_code(code)
        minutes = int(frequency.removesuffix("m"))
        if frequency not in {"1m", "5m", "15m", "30m", "60m"}:
            raise ValueError(f"不支持的分钟线周期: {frequency}")
        key = f"m{minutes}"
        anchor = end_date + pd.Timedelta(days=1)
        rows: dict[pd.Timestamp, dict] = {}
        for _ in range(1000):
            params = {"param": f"{market_code},{key},{anchor:%Y%m%d%H%M},320"}
            for attempt in range(3):
                try:
                    response = self.session.get(self.MINUTE_KLINE_URL, params=params, timeout=10)
                    response.raise_for_status()
                    payload = response.json()
                    break
                except (requests.RequestException, ValueError):
                    if attempt == 2:
                        raise
                    time.sleep(self.rate_limit_delay * (attempt + 1))
            page = (payload.get("data") or {}).get(market_code, {}).get(key) or []
            if not page:
                raise ValueError(f"{code} 历史分钟线不足，无法覆盖 {start_date.date()} 至 {end_date.date()}")
            oldest = pd.Timestamp(str(page[0][0]))
            if oldest >= anchor:
                raise ValueError(f"{code} 历史分钟线分页没有向前推进")
            for item in page:
                stamp = pd.Timestamp(str(item[0]))
                if start_date <= stamp.normalize() <= end_date:
                    rows[stamp] = {
                        "open": float(item[1]), "close": float(item[2]),
                        "high": float(item[3]), "low": float(item[4]),
                        "volume": float(item[5]),
                    }
            if oldest.normalize() < start_date:
                frame = pd.DataFrame.from_dict(rows, orient="index").sort_index()
                frame.index.name = "time"
                return frame
            anchor = oldest
            time.sleep(self.rate_limit_delay)
        raise ValueError(f"{code} 历史分钟线分页超过上限")

    def fetch_minute_kline(
        self,
        code: str,
        count: int = 100,
        frequency: str = "15m"
    ) -> pd.DataFrame:
        """
        获取分钟级 K 线数据

        Args:
            code: 6 位股票代码（如 "600519"）或市场代码（如 "sh600519"）
            count: 返回条数（腾讯接口限制）
            frequency: K 线周期，支持 1m/5m/15m/30m/60m

        Returns:
            DataFrame，列为 time, open, close, high, low, volume
        """
        # 转换为腾讯市场代码
        market_code = _to_tencent_code(code)

        # 解析周期数
        ts = int(frequency[:-1]) if frequency[:-1].isdigit() else 1

        # 构建请求
        url = self.MINUTE_KLINE_URL
        params = {
            "param": f"{market_code},m{ts},,{count}"
        }

        resp = self.session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # 解析响应: data[market_code]['m1'/'m5'...]
        data_dict = data.get("data", {})
        if not data_dict:
            return pd.DataFrame()

        stock_data = list(data_dict.values())[0]
        m_key = f"m{ts}"
        kline_list = stock_data.get(m_key, [])

        if not kline_list:
            return pd.DataFrame()

        # 每条记录: [时间戳, 开, 收, 高, 低, 量, {}, 换手率]
        rows = []
        for item in kline_list:
            if len(item) >= 6:
                time_str = item[0]
                # 时间戳格式: "202606041003" → "2026-06-04 10:03"
                time_dt = f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]} {time_str[8:10]}:{time_str[10:12]}"
                rows.append({
                    "time": pd.to_datetime(time_dt),
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]),
                })

        df = pd.DataFrame(rows)
        df.set_index("time", inplace=True)
        df.index.name = ""

        return df


# --------------------------- 工厂函数 --------------------------- #

def create_source(source_type: str) -> KLineSource:
    """根据配置类型创建数据源实例"""
    if source_type == "tushare":
        return TushareSource()
    elif source_type in ("tencent", "tencent_finance"):
        return TencentSource()
    else:
        raise ValueError(f"未知数据源类型：{source_type}，支持: tushare / tencent")


def create_minute_source(source_type: str) -> TencentMinuteSource:
    """创建分钟级数据源"""
    if source_type in ("tencent", "tencent_finance"):
        return TencentMinuteSource()
    else:
        raise ValueError(f"分钟级数据源仅支持 tencent，收到: {source_type}")


# --------------------------- 全局配置辅助函数 --------------------------- #

def get_global_source_config() -> dict:
    """从 fetch_kline.yaml 加载全局数据源配置。

    Returns:
        包含以下键的字典:
        - data_source: 数据源类型 ("tencent" 或 "tushare")
        - tencent: 腾讯配置段 (如有)
        - tushare: Tushare 配置段 (如有)
    """
    import yaml
    cfg_path = Path(__file__).resolve().parent.parent / "config" / "fetch_kline.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    return {
        "data_source": cfg.get("data_source", "tencent"),
        "tencent": cfg.get("tencent", {}),
        "tushare": cfg.get("tushare", {}),
    }


def create_source_from_global_config() -> KLineSource:
    """使用全局 fetch_kline.yaml 配置创建并初始化数据源。

    这是各 pipeline 模块获取数据源的推荐方式。
    """
    global_cfg = get_global_source_config()
    source_type = global_cfg.get("data_source", "tencent")
    source = create_source(source_type)
    source.initialize(global_cfg)
    return source
