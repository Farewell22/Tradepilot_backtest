"""Audited raw bank-stock inputs in the defensive strategy's parquet format."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pandas as pd
import numpy as np
import pyarrow.parquet as pq


CODE = "601288.SH"
DEFAULT_DATA_DIR = Path("data/backtest_data/5m_price")
DEFAULT_DIVIDENDS_PATH = Path(__file__).resolve().parents[1] / "amv_winning_defensive/dividends_601288.csv"
HISTORY_START = pd.Timestamp("2019-01-01")
AUDITED_END = pd.Timestamp("2025-12-31")
# These seven source days have vol scaled by 100 across multiple stocks.
# Verified by amount/vol: raw ratio ~0.01 of OHLC, corrected ratio within OHLC.
SOURCE_VOLUME_DIVISORS = dict.fromkeys(
    ("20240403", "20240419", "20240426", "20240430", "20240524", "20240531", "20240614"), 100
)


def load_stock_history(data_dir: Path, last_date: pd.Timestamp, *, code: str = CODE) -> tuple[pd.DataFrame, dict]:
    """Load raw bars including pre-start warm-up; inspect raw-price evidence."""
    from python.strategies.amv_winning.runner import STOCK_BANK_CODES, _normalize_intraday

    if code not in STOCK_BANK_CODES:
        raise ValueError(f"不支持的银行股票: {code}")
    label = {CODE: "农业银行", "601939.SH": "建设银行", "600036.SH": "招商银行"}[code]

    last_date = pd.Timestamp(last_date).normalize()
    files = sorted(path for path in data_dir.glob("*/*.parquet")
                   if path.stem.isdigit() and len(path.stem) == 8
                   and HISTORY_START <= pd.to_datetime(path.stem, format="%Y%m%d") <= last_date)
    if not files:
        raise ValueError(f"{label} {code} 没有可用历史行情: {data_dir}")

    def read_day(path: Path) -> pd.DataFrame:
        frame = pq.read_table(path, filters=[("code", "==", code)],
                              columns=["trade_time", "open", "high", "low", "close", "vol", "amount"]).to_pandas()
        if frame.empty:
            return frame
        frame["trade_time"] = pd.to_datetime(frame["trade_time"], errors="raise")
        date = pd.to_datetime(path.stem, format="%Y%m%d")
        expected = set(pd.date_range(date + pd.Timedelta(hours=9, minutes=35), periods=24, freq="5min"))
        expected.update(pd.date_range(date + pd.Timedelta(hours=13, minutes=5), periods=24, freq="5min"))
        actual = set(frame["trade_time"])
        if actual not in (expected, expected | {date + pd.Timedelta(hours=9, minutes=30)}):
            raise ValueError(f"{label} {path.stem} 5分钟行情不完整")
        prices = frame[["open", "high", "low", "close"]]
        if (not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any()
                or (frame["high"] < prices.max(axis=1)).any()
                or (frame["low"] > prices.min(axis=1)).any()):
            raise ValueError(f"{label} {path.stem} OHLC 存在非有限、非正或区间矛盾的价格")
        flow = frame[["vol", "amount"]]
        if not np.isfinite(flow.to_numpy()).all() or (flow < 0).any().any():
            raise ValueError(f"{label} {path.stem} 成交量/额必须为有限非负数")
        traded = frame.loc[frame["vol"] > 0]
        vwap = traded["amount"].astype(float) / traded["vol"].astype(float)
        match = vwap.between(traded["low"] - .02, traded["high"] + .02).mean()
        divisor = SOURCE_VOLUME_DIVISORS.get(path.stem)
        if match < .95 and divisor is not None:
            corrected_match = (vwap * divisor).between(traded["low"] - .02, traded["high"] + .02).mean()
            if corrected_match >= .95:
                frame["vol"] = frame["vol"] / divisor
                frame.attrs["volume_correction"] = (path.stem, divisor)
                match = corrected_match
        if not pd.notna(match) or match < .95:
            raise ValueError(f"{label} {path.stem} 价格疑似复权，不能另加现金分红")
        return frame

    with ThreadPoolExecutor(max_workers=4) as pool:
        parts = [part for part in pool.map(read_day, files) if not part.empty]
    if not parts:
        raise ValueError(f"{label} {code} 没有可用历史行情: {data_dir}")
    raw = pd.concat(parts, ignore_index=True)
    traded = raw.loc[raw["vol"] > 0]
    vwap = traded["amount"].astype(float) / traded["vol"].astype(float)
    match = vwap.between(traded["low"] - .02, traded["high"] + .02).mean()
    if not pd.notna(match) or match < .95:
        raise ValueError(f"{label}价格与成交额/成交量不一致，疑似复权行情；不能另加现金分红")
    frame = _normalize_intraday(raw.rename(columns={"trade_time": "date", "vol": "volume"}))
    audit = {
        "code": code, "price_basis": "raw_verified_with_amount_per_share",
        "vwap_in_bar_range_pct": float(match * 100), "bar_count": len(frame),
        "first_date": frame["date"].min().isoformat(), "last_date": frame["date"].max().isoformat(),
        "source_files": [{"path": str(path.resolve()), "size": path.stat().st_size,
                          "mtime_ns": path.stat().st_mtime_ns} for path in files],
        "volume_corrections": {part.attrs["volume_correction"][0]: {
            "divisor": part.attrs["volume_correction"][1], "reason": "verified_amount_per_share"
        } for part in parts if "volume_correction" in part.attrs},
    }
    return frame, audit


def load_stock_dividends(path: Path) -> dict[pd.Timestamp, float]:
    # Reuse the same public-announcement amounts as the adjacent strategy.
    from python.strategies.amv_winning_defensive.runner import load_dividend_events

    result = load_dividend_events(path)
    if any(pd.isna(date) or not 0 < amount < float("inf") for date, amount in result.items()):
        raise ValueError("分红表包含缺失日期或非有限正数金额")
    return result


def snapshot_stock_inputs(output_dir: Path, bars: pd.DataFrame, dividends_path: Path, audit: dict,
                          *, amv_path: Path, primary_path: Path, code: str = CODE,
                          extra_sources: tuple[str, ...] = (), primary_code: str = "512100.SH",
                          extra_inputs: dict[str, Path] | None = None) -> None:
    """Snapshot precisely the filtered stock inputs and execution sources."""
    inputs = output_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    bars.to_csv(inputs / f"{code}.csv", index=False, encoding="utf-8-sig", float_format="%.17g")
    dividend_file = f"dividends_{code[:6]}.csv"
    (inputs / dividend_file).write_bytes(dividends_path.read_bytes())
    (inputs / "0AMV.csv").write_bytes(amv_path.read_bytes())
    (inputs / f"{primary_code}.csv").write_bytes(primary_path.read_bytes())
    root = Path(__file__).resolve().parents[3]
    sources = (
        "python/strategies/amv_winning/runner.py", "python/strategies/amv_winning/bank_stock.py",
        "python/strategies/amv_winning_defensive/runner.py", "python/factors/z_indicators.py",
        "python/scoring/brick_indicator.py", "python/backtest/broker.py",
        "python/task_registry.py", "python/run_backtest.py",
    ) + extra_sources
    snapshot_files = [inputs / f"{code}.csv", inputs / dividend_file,
                      inputs / "0AMV.csv", inputs / f"{primary_code}.csv"]
    for name, source in (extra_inputs or {}).items():
        if Path(name).name != name or (inputs / name).exists():
            raise ValueError(f"附加输入文件名无效或冲突: {name}")
        target = inputs / name
        target.write_bytes(source.read_bytes())
        snapshot_files.append(target)
    for source in sources:
        target = output_dir / "code_snapshot" / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / source).read_bytes())
        snapshot_files.append(target)
    manifest = {"stock": audit, "sha256": {
        str(path.relative_to(output_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in snapshot_files
    }}
    (output_dir / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
