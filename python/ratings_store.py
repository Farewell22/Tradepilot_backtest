"""评分运行历史存储（JSON 文件持久化）。

存储布局::

    python/data/ratings/
    ├── index.json                 # 所有运行的元数据索引
    └── {run_id}/
        ├── meta.json              # 单次运行元数据
        └── ratings.json           # 评分结果数组

每次评分创建一个 run，包含股票列表、方法、模式和评分明细。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RUN_ID_RE = re.compile(r"^[\w\-\.]+$")

_BASE_DIR = Path(__file__).parent / "data" / "ratings"
_LOCK = threading.Lock()


def _ensure_dirs() -> None:
    _BASE_DIR.mkdir(parents=True, exist_ok=True)


def _index_path() -> Path:
    return _BASE_DIR / "index.json"


def _run_dir(run_id: str) -> Path:
    return _BASE_DIR / run_id


def _read_index() -> list[dict]:
    _ensure_dirs()
    path = _index_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 runs index 失败: %s", e)
        return []


def _write_index(runs: list[dict]) -> None:
    _ensure_dirs()
    path = _index_path()
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(runs, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _validate_run_id(run_id: str) -> None:
    if not run_id or not _RUN_ID_RE.match(run_id):
        raise ValueError(f"非法 run_id: {run_id!r}")


def next_run_id(prefix: str = "run") -> str:
    """生成下一个自增 run_id，形如 run-001、run-002。"""
    with _LOCK:
        runs = _read_index()
        max_seq = 0
        for r in runs:
            rid = r.get("id", "")
            if rid.startswith(f"{prefix}-"):
                tail = rid[len(prefix) + 1:]
                if tail.isdigit():
                    max_seq = max(max_seq, int(tail))
        return f"{prefix}-{max_seq + 1:03d}"


def list_runs(method: str | None = None, mode: str | None = None) -> list[dict]:
    """列出所有运行元数据，按创建时间倒序。"""
    runs = _read_index()
    if method:
        runs = [r for r in runs if r.get("method") == method]
    if mode:
        runs = [r for r in runs if r.get("mode") == mode]
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return runs


def get_run(run_id: str) -> dict | None:
    """获取单次运行的完整数据（含 ratings）。"""
    _validate_run_id(run_id)
    d = _run_dir(run_id)
    meta_path = d / "meta.json"
    if not meta_path.exists():
        return None
    with meta_path.open("r", encoding="utf-8") as f:
        meta = json.load(f)
    ratings = get_ratings(run_id)
    return {**meta, "ratings": ratings}


def get_ratings(run_id: str) -> list[dict]:
    _validate_run_id(run_id)
    path = _run_dir(run_id) / "ratings.json"
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("读取 ratings 失败 run_id=%s: %s", run_id, e)
        return []


def create_run(
    run_id: str,
    name: str,
    method: str,
    mode: str,
    stocks: list[dict],
    ratings: list[dict],
) -> dict:
    """创建一次评分运行，保存元数据和评分结果。

    Args:
        run_id: 运行 ID（由调用方传入或调用 next_run_id 生成）
        name: 运行名称（可空）
        method: 评分方法（b1 / brick）
        mode: 评分模式（aggressive / conservative）
        stocks: 入参股票列表 [{code, name}]
        ratings: 评分结果列表
    """
    _validate_run_id(run_id)
    with _LOCK:
        _ensure_dirs()
        d = _run_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        meta = {
            "id": run_id,
            "name": name or f"{method}-{run_id}",
            "method": method,
            "mode": mode,
            "stock_count": len(stocks),
            "created_at": now,
        }
        with (d / "meta.json").open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        with (d / "ratings.json").open("w", encoding="utf-8") as f:
            json.dump(ratings, f, ensure_ascii=False, indent=2)

        runs = _read_index()
        runs = [r for r in runs if r.get("id") != run_id]
        runs.append(meta)
        _write_index(runs)
        return {**meta, "ratings": ratings}


def rename_run(run_id: str, name: str) -> dict | None:
    _validate_run_id(run_id)
    with _LOCK:
        d = _run_dir(run_id)
        meta_path = d / "meta.json"
        if not meta_path.exists():
            return None
        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["name"] = name
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        runs = _read_index()
        for r in runs:
            if r.get("id") == run_id:
                r["name"] = name
                break
        _write_index(runs)
        return meta


def delete_run(run_id: str) -> bool:
    _validate_run_id(run_id)
    with _LOCK:
        d = _run_dir(run_id)
        if not d.exists():
            return False
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        runs = _read_index()
        runs = [r for r in runs if r.get("id") != run_id]
        _write_index(runs)
        return True
