# -*- coding: utf-8 -*-
"""
数据选择策略模块
根据当前时间场景自动选择合适的 K 线数据源和周期
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import Enum

import pandas as pd

from data_source import TencentSource, TencentMinuteSource, is_in_trading_hours, create_source, create_minute_source

logger = logging.getLogger("data_strategy")


class Scenario(Enum):
    """使用场景"""
    INTRADAY_MONITORING = "intraday_monitoring"      # 盘中实时监控
    AFTER_HOURS_REVIEW = "after_hours_review"        # 盘后复盘
    PRE_MARKET = "pre_market"                        # 早盘开盘前
    BATCH_SCORING = "batch_scoring"                  # 批量评分


class DataStrategy:
    """数据选择策略"""

    @staticmethod
    def detect_scenario() -> Scenario:
        """根据当前时间和用途自动选择场景"""
        now = datetime.now()
        hour, minute = now.hour, now.minute
        weekday = now.weekday()

        # 周末默认为盘后复盘
        if weekday >= 5:
            return Scenario.AFTER_HOURS_REVIEW

        # 交易时段
        if (hour == 9 and minute >= 30) or (10 <= hour < 11) or (hour == 11 and minute <= 30):
            return Scenario.INTRADAY_MONITORING
        if 13 <= hour < 15:
            return Scenario.INTRADAY_MONITORING

        # 早盘
        if 8 <= hour < 9 or (hour == 9 and minute < 30):
            return Scenario.PRE_MARKET

        # 盘后
        if hour >= 15 or hour < 8:
            return Scenario.AFTER_HOURS_REVIEW

        # 其他情况
        return Scenario.BATCH_SCORING

    @staticmethod
    def get_kline(
        code: str,
        scenario: Scenario | None = None,
        count: int = 100,
        source_type: str = "tencent"
    ) -> pd.DataFrame:
        """
        根据场景获取合适的 K 线数据

        Args:
            code: 股票代码
            scenario: 指定场景，None 则自动检测
            count: 返回条数
            source_type: 数据源类型，默认 tencent

        Returns:
            K 线数据 DataFrame
        """
        if scenario is None:
            scenario = DataStrategy.detect_scenario()

        daily_source = create_source(source_type)
        minute_source = create_minute_source(source_type)

        if scenario == Scenario.INTRADAY_MONITORING:
            # 盘中：优先分钟线，失败回退日线
            try:
                df = minute_source.fetch_minute_kline(code, count, frequency="15m")
                if not df.empty:
                    logger.debug(f"使用 15 分钟 K 线: {code}")
                    return df
            except Exception as e:
                logger.warning(f"分钟线获取失败，回退日线: {code}, {e}")

            # 回退到日线
            logger.debug(f"回退使用日线 K 线: {code}")
            return daily_source.fetch_kline(code, count=count)

        elif scenario == Scenario.AFTER_HOURS_REVIEW:
            # 盘后：只用日线（收盘价）
            logger.debug(f"盘后复盘，使用日线 K 线: {code}")
            return daily_source.fetch_kline(code, count=count)

        elif scenario == Scenario.PRE_MARKET:
            # 早盘：用昨日日线
            end_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=count * 2)).strftime("%Y%m%d")
            logger.debug(f"早盘，使用昨日日线 K 线: {code}, end={end_date}")
            return daily_source.fetch_kline(code, start=start_date, end=end_date, count=count)

        else:  # BATCH_SCORING
            # 批量评分：日线
            logger.debug(f"批量评分，使用日线 K 线: {code}")
            return daily_source.fetch_kline(code, count=count)
