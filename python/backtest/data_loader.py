"""数据加载层。

职责：
1. 启动时预加载日线数据（按 [start - lookback_days, end] 范围）到内存。
2. 提供防未来函数的访问接口：as_of_date 切片。
3. 盘中按需读取单股某日的 5min bar 用于执行模拟。

性能优化：
- 并行读取 parquet（多进程，按文件分片）
- 按 (code, date) 排序后，所���切片查询用索引快速完成
"""
from __future__ import annotations

import glob
import logging
from multiprocessing import Pool
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


def _load_and_aggregate_one_file(path_str: str) -> pd.DataFrame:
    """worker：读一个 parquet 文件并聚合为日线。"""
    df_5min = pq.read_table(path_str).to_pandas()
    if df_5min.empty:
        return pd.DataFrame()
    g = df_5min.groupby("code", sort=False)
    daily = pd.DataFrame({
        "code": g["code"].first(),
        "date": g["date"].first(),
        "open": g["open"].first(),
        "close": g["close"].last(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "vol": g["vol"].sum(),
        "amount": g["amount"].sum(),
        "pre_close": g["pre_close"].apply(
            lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan
        ),
    }).reset_index(drop=True)
    daily = daily[daily["pre_close"].notna() & (daily["pre_close"] > 0)]
    daily["pct_chg"] = (daily["close"] - daily["pre_close"]) / daily["pre_close"] * 100
    return daily


class DataLoader:
    def __init__(
        self,
        data_dir: Path,
        start_date: str,
        end_date: str,
        lookback_days: int = 120,
        n_workers: int = 1,
    ):
        """
        Args:
            data_dir: 5min parquet 根目录
            start_date / end_date: 回测区间（YYYYMMDD）
            lookback_days: 指标计算历史窗口
            n_workers: 并行加载 parquet 的进程数
        """
        self.data_dir = Path(data_dir)
        self.start_date = start_date
        self.end_date = end_date
        self.lookback_days = lookback_days
        self.n_workers = n_workers

        self.trading_days: list[str] = self._scan_trading_days()
        self.daily_df: pd.DataFrame = self._load_all_daily()

        # 加速查询：在 daily_df 上建索引
        self._build_indexes()

    def _scan_trading_days(self) -> list[str]:
        all_files = sorted(glob.glob(str(self.data_dir / "*" / "*.parquet")))
        days = [Path(f).stem for f in all_files]
        end_idx = next((i for i, d in enumerate(days) if d > self.end_date), len(days))
        start_idx = next((i for i, d in enumerate(days) if d >= self.start_date), 0)
        load_start_idx = max(0, start_idx - self.lookback_days)
        return days[load_start_idx:end_idx]

    def _load_all_daily(self) -> pd.DataFrame:
        logger.info(f"Loading {len(self.trading_days)} trading days "
                    f"with {self.n_workers} workers...")

        paths = []
        for date_str in self.trading_days:
            year = date_str[:4]
            path = self.data_dir / year / f"{date_str}.parquet"
            if path.exists():
                paths.append(str(path))

        if self.n_workers <= 1:
            rows = [_load_and_aggregate_one_file(p) for p in paths]
        else:
            with Pool(self.n_workers) as pool:
                rows = pool.map(_load_and_aggregate_one_file, paths, chunksize=8)

        df = pd.concat(rows, ignore_index=True)
        df = df.sort_values(["code", "date"]).reset_index(drop=True)
        logger.info(f"Loaded daily df: {len(df):,} rows, {df['code'].nunique()} stocks")
        return df

    def _build_indexes(self) -> None:
        """构建查询索引：按 date 分组的行号范围。

        daily_df 已按 (code, date) 排序，我们再构建一个 date → 行集合的查找。
        """
        # date 索引：用于 prefilter 时按日期切片
        self._date_groups = {date: g.index for date, g in
                             self.daily_df.groupby("date", sort=False)}

    def iter_trading_days(self) -> Iterator[str]:
        for d in self.trading_days:
            if self.start_date <= d <= self.end_date:
                yield d

    def get_history_for_codes(
        self, codes: list[str], as_of_date: str, lookback: int = 120
    ) -> dict[str, pd.DataFrame]:
        """获取指定 codes 的历史日线（截止 as_of_date 不含，前 lookback 天）。

        只取指定股票的历史，避免为单次查询复制全市场数据。
        """
        if not codes:
            return {}
        days_before = [d for d in self.trading_days if d < as_of_date]
        if len(days_before) < lookback:
            return {}
        window_days = set(days_before[-lookback:])

        code_set = set(codes)
        mask = (
            self.daily_df["code"].isin(code_set)
            & self.daily_df["date"].isin(window_days)
        )
        sub = self.daily_df[mask]
        return {code: g.set_index("date") for code, g in sub.groupby("code", sort=False)}

    def get_5min_bars_multi(self, codes: list[str], date: str) -> dict[str, pd.DataFrame]:
        """批量读取多只股票当日的 5min bar（盘中执行用）。"""
        if not codes:
            return {}
        year = date[:4]
        path = self.data_dir / year / f"{date}.parquet"
        if not path.exists():
            return {}
        df = pq.read_table(path, filters=[("code", "in", codes)]).to_pandas()
        return {
            code: g.sort_values("trade_time").reset_index(drop=True)
            for code, g in df.groupby("code", sort=False)
        }

    # ── 旧 API 保留（向后兼容） ──
    def get_history_for_universe(
        self, as_of_date: str, lookback: int = 120
    ) -> dict[str, pd.DataFrame]:
        days_before = [d for d in self.trading_days if d < as_of_date]
        if len(days_before) < lookback:
            return {}
        window_days = days_before[-lookback:]
        mask = self.daily_df["date"].isin(window_days)
        sub = self.daily_df[mask]
        return {code: g.set_index("date") for code, g in sub.groupby("code", sort=False)}

    def get_universe_codes(self, as_of_date: str) -> list[str]:
        sub = self.daily_df[self.daily_df["date"] == as_of_date]
        return sub["code"].tolist()
