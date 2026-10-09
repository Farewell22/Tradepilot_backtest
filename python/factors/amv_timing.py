"""0AMV 择时（MACD + MA 组合仓位管理）。

在 0AMV 上预计算 MACD(12,26,9) + SMA(5/10/20/60) 指标，
组合成连续仓位比例 (0.0~1.0) 用于每日买入数量控制，
并提供精细化的强制减仓信号。

接口与旧版一致：
- get_position_ratio(date_str) -> float  (0.0~1.0)
- get_force_sell_pct(date_str) -> float  (0.0~1.0)
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class TimingSignal:
    """0AMV 择时信号发生器。"""

    def __init__(self, csv_path: Path | None = None):
        self.csv_path = csv_path
        self._data: dict[str, dict] = {}
        if csv_path is not None:
            self._load()

    def _load(self) -> None:
        if self.csv_path is None or not self.csv_path.exists():
            logger.warning(f"0AMV 数据不存在: {self.csv_path}，择时将禁用")
            return

        df = pd.read_csv(self.csv_path, encoding="utf-8-sig")
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
        df = df.sort_values("date").reset_index(drop=True)

        close = df["close"]
        df["day_pct"] = close.pct_change() * 100
        df["three_day_pct"] = close.pct_change(periods=3) * 100

        # ── MACD(12,26,9) ──
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        df["DIFF"] = ema12 - ema26
        df["DEA"] = df["DIFF"].ewm(span=9, adjust=False).mean()
        df["MACD_hist"] = (df["DIFF"] - df["DEA"]) * 2

        # ── SMA ──
        df["MA5"] = close.rolling(5).mean()
        df["MA10"] = close.rolling(10).mean()
        df["MA20"] = close.rolling(20).mean()
        df["MA60"] = close.rolling(60).mean()

        # 初始化 _data 字典
        for _, row in df.iterrows():
            date = row["date"]
            fields = {
                "close": float(row["close"]),
                "day_pct": None if pd.isna(row["day_pct"]) else float(row["day_pct"]),
                "three_day_pct": None if pd.isna(row["three_day_pct"]) else float(row["three_day_pct"]),
                "DIFF": self._safe(row["DIFF"]),
                "DEA": self._safe(row["DEA"]),
                "MACD_hist": self._safe(row["MACD_hist"]),
                "MA5": self._safe(row["MA5"]),
                "MA10": self._safe(row["MA10"]),
                "MA20": self._safe(row["MA20"]),
                "MA60": self._safe(row["MA60"]),
            }
            self._data[date] = fields

        logger.info(
            f"已加载 {len(self._data)} 天 0AMV 数据 (MACD+MA) ({self.csv_path})"
        )

    @staticmethod
    def _safe(val) -> float | None:
        return None if pd.isna(val) else float(val)

    # ── 子评分 ──────────────────────────────────────

    def _calc_macd_score(self, d: dict) -> float:
        """MACD 趋势评分（权重 40%）。

        DIFF > DEA + MACD_hist > 0  → 1.0  强多头
        DIFF > DEA                   → 0.7  弱多头
        DIFF < DEA + MACD_hist 拐头 → 0.4  可能见底（暂简化：仅判断 DIFF<DEA+hist>=-1）
        DIFF < DEA                   → 0.2  空头
        DIFF < DEA + MACD_hist < 0  → 0.0  深度空头
        """
        diff = d.get("DIFF")
        dea = d.get("DEA")
        hist = d.get("MACD_hist")
        if diff is None or dea is None:
            return 0.5

        if hist is not None and hist > 0 and diff > dea:
            return 1.0
        if diff > dea:
            return 0.7
        if hist is not None and hist < 0 and diff < dea:
            return 0.0
        if diff < dea:
            return 0.2
        return 0.5

    def _calc_ma_score(self, d: dict) -> float:
        """MA 排列评分（权重 30%）。

        每站上一条均线 +0.25（最多 1.0）。
        空头排列（MA5 < MA10 < MA20）额外 -0.15。
        """
        close = d.get("close")
        if close is None:
            return 0.5

        score = 0.0
        count = 0
        for key in ("MA5", "MA10", "MA20", "MA60"):
            ma = d.get(key)
            if ma is not None:
                count += 1
                if close > ma:
                    score += 0.25

        if count == 0:
            return 0.5

        # 空头排列惩罚
        ma5, ma10, ma20 = (d.get(k) for k in ("MA5", "MA10", "MA20"))
        if all(v is not None for v in (ma5, ma10, ma20)) and ma5 < ma10 < ma20:
            score -= 0.15

        return max(0.0, min(1.0, score))

    def _calc_momentum_score(self, d: dict) -> float:
        """短期动量评分（权重 20%）。

        单日涨 > 0 → 0.5 分
        三日涨 > 3% → +0.5, > 0% → +0.25
        """
        score = 0.0
        dp = d.get("day_pct")
        tdp = d.get("three_day_pct")

        if dp is not None and dp > 0:
            score += 0.5
        if tdp is not None:
            if tdp > 3:
                score += 0.5
            elif tdp > 0:
                score += 0.25

        return min(1.0, score)

    def _calc_day_adjust(self, d: dict) -> float:
        """日涨跌微调（权重 10%）。

        涨 → +0.1, 跌超 3% → -0.1
        """
        dp = d.get("day_pct")
        if dp is None:
            return 0.0
        if dp > 0:
            return 0.1
        if dp < -3:
            return -0.1
        return 0.0

    # ── 公开接口 ────────────────────────────────────

    def get_position_ratio(self, date_str: str) -> float:
        """组合仓位比例 (0.0~1.0)。

        无数据 → 1.0（择时未启用，满仓）
        找不到日期 → 0.0（保守）
        无 MACD 指标 → 降级到旧版阈值逻辑
        """
        if not self._data:
            return 1.0

        d = self._data.get(date_str)
        if not d:
            return 0.0

        # 降级：MACD 数据尚未充足时用旧版阈值
        if d.get("DIFF") is None:
            return self._legacy_position_ratio(d)

        ratio = (
            self._calc_macd_score(d) * 0.40
            + self._calc_ma_score(d) * 0.30
            + self._calc_momentum_score(d) * 0.20
            + self._calc_day_adjust(d) * 0.10
        )
        return max(0.0, min(1.0, ratio))

    def is_bear_regime(self, date_str: str) -> bool:
        """牛熊识别：0AMV 的 close < MA60 且 MA60 在下降通道。

        用于熊市时提高评分门槛，减少假 B1 信号。
        """
        if not self._data:
            return False

        d = self._data.get(date_str)
        if not d:
            return False

        close = d.get("close")
        ma60 = d.get("MA60")
        if close is None or ma60 is None:
            return False

        return close < ma60

    def get_force_sell_pct(self, date_str: str) -> float:
        """强制减仓比例 (0.0~1.0)。

        基于大跌日 + 均线破位触发。MACD 空头趋势由 position_ratio 控制
        （限制买入），force_sell 仅负责已持仓的风险控制。
        """
        if not self._data:
            return 0.0

        d = self._data.get(date_str)
        if not d:
            return 0.0

        sell_pct = 0.0
        dp = d.get("day_pct")

        # 暴跌保护（原版 2 档 → 3 档更精细）
        if dp is not None:
            if dp <= -5:
                sell_pct = 1.0
            elif dp <= -3:
                sell_pct = 0.5
            elif dp <= -1.5:
                sell_pct = 0.2

        return max(0.0, min(1.0, sell_pct))

    def _legacy_position_ratio(self, d: dict) -> float:
        """旧版阈值逻辑（降级用：数据不足前 60 天）。"""
        dp = d.get("day_pct")
        tdp = d.get("three_day_pct")
        if dp is None:
            return 0.0

        if dp >= 4:
            ratio = 1.0
        elif dp >= 2:
            ratio = 0.75
        elif dp >= 0:
            ratio = 0.50
        else:
            ratio = 0.0

        if tdp is not None and tdp >= 4:
            ratio = max(ratio, 0.75)

        return ratio
