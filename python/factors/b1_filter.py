"""B1 评分过滤层。

复用 python/scoring/stock_rater.py 的 rate_one() 评分逻辑。
原 rate_one() 接受 CSV 文件路径，我们通过临时 monkey-patch read_csv 让其从内存读取。

支持单进程和多进程评分：
- filter_b1_candidates() — 单进程
- filter_b1_candidates_parallel() — 多进程（每个 worker 独立 monkey-patch，安全）
"""
from __future__ import annotations

import logging
from multiprocessing import Pool
from pathlib import PurePosixPath
from typing import Optional

import pandas as pd

from python.scoring import stock_rater as sr
from python.scoring.stock_rater import (
    DEFAULT_WEIGHTS,
    KLineRow,
    RatingResult,
    load_config,
    rate_one,
)

logger = logging.getLogger(__name__)


def _df_to_klinerows(df: pd.DataFrame) -> list[KLineRow]:
    rows = []
    for _, r in df.iterrows():
        rows.append(KLineRow(
            date=str(r["date"]),
            open=float(r["open"]),
            close=float(r["close"]),
            high=float(r["high"]),
            low=float(r["low"]),
            volume=float(r["vol"]),
        ))
    return rows


def rate_one_from_df(
    code: str, df: pd.DataFrame, weights: dict, config: Optional[dict] = None
) -> Optional[RatingResult]:
    """从内存 DataFrame 评分。

    monkey-patch stock_rater.read_csv，让 rate_one() 返回我们准备好的 KLineRow 列表。
    """
    df_reset = df.reset_index() if "date" not in df.columns else df
    rows = _df_to_klinerows(df_reset)
    if len(rows) < 20:
        return None

    fake_path = PurePosixPath(f"/__mem__/{code}.csv")
    original_read_csv = sr.read_csv
    try:
        sr.read_csv = lambda _fp: rows
        return rate_one(fake_path, weights, config)
    finally:
        sr.read_csv = original_read_csv


def filter_b1_candidates(
    candidates_history: dict[str, pd.DataFrame],
    weights: Optional[dict] = None,
    config: Optional[dict] = None,
    accepted_verdicts: Optional[tuple[str, ...]] = ("PASS", "WATCH"),
) -> list[RatingResult]:
    """单进程版本。

    accepted_verdicts=None 表示返回所有非 None 评分结果（含 FAIL），用于持久化保存。
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    out = []
    for code, df in candidates_history.items():
        try:
            result = rate_one_from_df(code, df, weights, config)
        except Exception as e:
            logger.warning(f"rate_one_from_df failed for {code}: {e}")
            continue
        if result is None:
            continue
        if accepted_verdicts is None or result.verdict in accepted_verdicts:
            out.append(result)
    return out


def _rate_one_worker(args: tuple) -> Optional[RatingResult]:
    """worker：在子进程中评分一只股票。

    每个子进程独立 import stock_rater，monkey-patch 互不影响。
    """
    code, df, weights, config = args
    try:
        return rate_one_from_df(code, df, weights, config)
    except Exception:
        return None


def filter_b1_candidates_parallel(
    candidates_history: dict[str, pd.DataFrame],
    weights: Optional[dict] = None,
    config: Optional[dict] = None,
    accepted_verdicts: Optional[tuple[str, ...]] = ("PASS", "WATCH"),
    n_workers: int = 4,
) -> list[RatingResult]:
    """多进程版本。

    候选少时（< 50）直接走单进程，避免进程启动开销。
    使用 imap（保序）确保结果与单进程一致 — 否则买入选择顺序会受 OS 调度影响。

    accepted_verdicts=None 表示返回所有非 None 评分结果（含 FAIL），用于持久化保存。
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    if n_workers <= 1 or len(candidates_history) < 50:
        return filter_b1_candidates(candidates_history, weights, config, accepted_verdicts)

    tasks = [(code, df, weights, config) for code, df in candidates_history.items()]
    out = []
    with Pool(n_workers) as pool:
        # imap 而不是 imap_unordered — 保持输入顺序
        for result in pool.imap(_rate_one_worker, tasks, chunksize=16):
            if result is None:
                continue
            if accepted_verdicts is None or result.verdict in accepted_verdicts:
                out.append(result)
    return out


def load_stock_rater_config():
    return load_config()
