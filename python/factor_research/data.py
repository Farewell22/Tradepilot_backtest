"""Validated research inputs and cache-first index retrieval."""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class ResearchDataError(RuntimeError):
    """Raised when a required research input cannot be made trustworthy."""


def _normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ResearchDataError(f"指数数据缺少列: {', '.join(sorted(missing))}")
    result = frame.loc[:, ["date", "open", "high", "low", "close", "volume"]].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    if result["date"].duplicated().any():
        raise ResearchDataError("指数数据存在重复日期")
    for column in result.columns.drop("date"):
        result[column] = pd.to_numeric(result[column], errors="raise")
    return result.sort_values("date").reset_index(drop=True)


def load_amv_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ResearchDataError(f"0AMV 数据不存在: {path}")
    raw = pd.read_csv(path, encoding="utf-8-sig")
    if not {"date", "close"}.issubset(raw.columns):
        raise ResearchDataError("0AMV 数据必须包含 date 和 close 列")
    columns = ["date", "close"]
    columns[1:1] = [column for column in ("open", "high", "low") if column in raw.columns]
    result = raw.loc[:, columns].copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    for column in result.columns.drop("date"):
        result[column] = pd.to_numeric(result[column], errors="raise")
    if result["date"].duplicated().any() or (result["close"] <= 0).any():
        raise ResearchDataError("0AMV 数据含重复日期或非正收盘价")
    return result.sort_values("date").reset_index(drop=True)


def download_full_index_history(code: str) -> pd.DataFrame:
    """Download the complete unadjusted daily history for a Chinese index."""
    import akshare as ak

    return ak.stock_zh_index_daily(symbol=code)


class IndexCache:
    def __init__(self, cache_root: Path, history_loader: Callable[[str], pd.DataFrame] = download_full_index_history):
        self.cache_root = Path(cache_root)
        self.history_loader = history_loader

    def load(self, code: str, start_date: str, end_date: str, refresh: bool = False) -> pd.DataFrame:
        path = self.cache_root / f"{code}.csv"
        cached = _normalize_ohlcv(pd.read_csv(path)) if path.exists() else None
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        cache_covers_range = cached is not None and (
            cached["date"].min() <= start + pd.Timedelta(days=7)
            and cached["date"].max() >= end - pd.Timedelta(days=7)
        )
        if cache_covers_range and not refresh:
            return cached
        try:
            downloaded = _normalize_ohlcv(self.history_loader(code))
            downloaded = downloaded.loc[downloaded["date"].between(start, end)].reset_index(drop=True)
            if downloaded.empty:
                raise ResearchDataError(f"指数下载为空: {code}")
            self.cache_root.mkdir(parents=True, exist_ok=True)
            downloaded.to_csv(path, index=False)
            return downloaded
        except Exception as error:
            if cached is not None:
                logger.warning("指数下载失败，使用缓存 %s: %s", path, error)
                return cached
            raise ResearchDataError(f"无法获取指数 {code}: {error}") from error


def load_market_close_panel(data_root: Path, start_date: str, end_date: str) -> pd.DataFrame:
    root = Path(data_root)
    paths = sorted(path for path in root.glob("*/*.parquet") if start_date <= path.stem <= end_date)
    if not paths:
        raise ResearchDataError(f"未找到 {start_date} 至 {end_date} 的市场 Parquet 数据")
    frames = []
    for path in paths:
        try:
            frame = pd.read_parquet(path, columns=["code", "date", "trade_time", "close"])
        except Exception as error:
            raise ResearchDataError(f"无法读取市场 Parquet: {path}") from error
        frame = frame.sort_values(["code", "trade_time"]).groupby("code", as_index=False).tail(1)
        frames.append(frame.loc[:, ["code", "date", "close"]])
    daily = pd.concat(frames, ignore_index=True)
    daily["date"] = pd.to_datetime(daily["date"], errors="raise").dt.normalize()
    return daily.pivot(index="date", columns="code", values="close").sort_index()
