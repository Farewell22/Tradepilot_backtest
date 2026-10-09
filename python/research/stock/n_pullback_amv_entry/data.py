"""Audited daily aggregation, resumable adjustment cache and market-calendar labels."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import requests

ROOT = Path(__file__).resolve().parents[4]
SOURCE_RUN = ROOT / "data/backtest_runs/amv_winning_defensive__20260928T143530Z__de469ebc"
STOCK_DIR = ROOT / "data/backtest_data/5m_price"
CACHE = ROOT / "data/factor_research_data/n_pullback_amv_entry"
TIMES = set(pd.date_range("2000-01-01 09:35", "2000-01-01 11:30", freq="5min").strftime("%H:%M"))
TIMES |= set(pd.date_range("2000-01-01 13:05", "2000-01-01 15:00", freq="5min").strftime("%H:%M"))
CACHE_VERSION = 1  # daily OHLC aggregation schema
PREPARATION_VERSION = 2  # stock universe excludes 689xxx CDRs


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_events(source_run: Path, start: str, end: str) -> pd.DatetimeIndex:
    manifest = json.loads((source_run / "run_manifest.json").read_text())
    if manifest.get("task_id") != "amv_winning_defensive" or manifest.get("status") != "complete":
        raise ValueError("来源必须是已完成的amv_winning_defensive运行")
    trades = pd.read_csv(source_run / "trades_601288.SH.csv")
    dates = pd.to_datetime(trades.loc[(trades.side == "buy") & (trades.code == "512100.SH"), "date"].astype(str), format="%Y%m%d")
    events = pd.DatetimeIndex(dates).unique().sort_values()
    events = events[(events >= pd.Timestamp(start)) & (events <= pd.Timestamp(end))]
    if events.empty:
        raise ValueError("请求区间没有主仓实际开仓日")
    return events


def aggregate_day(raw: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    raw = raw.copy()
    raw["trade_time"] = pd.to_datetime(raw.trade_time)
    if (raw.trade_time.dt.normalize() != date).any():
        raise ValueError("分钟日期与文件日期不一致")
    if raw.duplicated(["code", "trade_time"]).any():
        raise ValueError("股票分钟时间戳重复")
    raw = raw.sort_values(["code", "trade_time"])
    # Equity-like daily cache; final stock universe excludes CDRs separately.
    codes = raw.code.astype(str)
    raw = raw[((codes.str.endswith(".SH")) & codes.str.startswith("6"))
              | ((codes.str.endswith(".SZ")) & codes.str.startswith(("0", "3")))
              | codes.str.endswith(".BJ")].copy()
    prices = raw[["open", "high", "low", "close"]].to_numpy(dtype=float)
    raw["price_ok"] = np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
    raw["price_ok"] &= (raw.high >= raw[["open", "close", "low"]].max(axis=1))
    raw["price_ok"] &= (raw.low <= raw[["open", "close", "high"]].min(axis=1))
    minute = raw.trade_time.dt.hour * 60 + raw.trade_time.dt.minute
    expected_minutes = {int(t[:2]) * 60 + int(t[3:]) for t in TIMES}
    raw["regular"] = minute.isin(expected_minutes)
    raw["time_ok"] = raw.regular | minute.eq(570)
    grouped = raw.groupby("code", sort=True)
    daily = grouped.agg(open=("open", "first"), high=("high", "max"),
                        low=("low", "min"), close=("close", "last"),
                        volume=("vol", "sum"), n_bars=("vol", "size"), price_ok=("price_ok", "all"),
                        regular_bars=("regular", "sum"), time_ok=("time_ok", "all"))
    daily["complete"] = daily.regular_bars.eq(48) & daily.n_bars.isin([48, 49]) & daily.time_ok
    daily["valid"] = daily.price_ok & daily.complete & (daily.volume > 0)
    daily["date"] = date
    return daily.reset_index()


def stock_universe(daily: pd.DataFrame) -> pd.DataFrame:
    """689xxx are STAR depositary receipts, not A-share stocks (SSE factbook)."""
    return daily.loc[~daily.code.astype(str).str.startswith("689")].copy()


def adjust_prices(daily: pd.DataFrame, adjustments: pd.DataFrame) -> pd.DataFrame:
    if adjustments.duplicated(["date", "code"]).any():
        raise ValueError("复权因子日期/代码重复")
    result = daily.merge(adjustments[["date", "code", "adj_factor"]], on=["date", "code"],
                         how="left", validate="one_to_one")
    bad = result.valid & (~np.isfinite(result.adj_factor) | (result.adj_factor <= 0))
    if bad.any():
        examples = result.loc[bad, ["date", "code"]].head(8).astype(str).to_dict("records")
        raise ValueError(f"有效行情缺失复权因子，不允许前填: {examples}; count={bad.sum()}")
    for name in ("open", "high", "low", "close"):
        result[name] = result[name] * result.adj_factor
    return result


def forward_labels(daily: pd.DataFrame, events, calendar: pd.DatetimeIndex,
                   horizons=(5, 10, 20)) -> pd.DataFrame:
    """Exact market endpoints; align once to avoid per-label pandas indexing."""
    daily = daily.loc[daily.valid].set_index("date")
    if daily.index.has_duplicates:
        raise ValueError("个股日线日期重复")
    columns = ["open", "close"] + (["low"] if "low" in daily else [])
    aligned = daily[columns].reindex(calendar)
    opens = aligned.open.to_numpy(dtype=float)
    closes = aligned.close.to_numpy(dtype=float)
    lows = aligned.low.to_numpy(dtype=float) if "low" in aligned else None
    rows = []
    for date in events:
        i = calendar.get_indexer([date])[0]
        if i < 0:
            raise ValueError("开仓日不在市场交易日历中")
        entry_date = calendar[i + 1] if i + 1 < len(calendar) else pd.NaT
        entry_open = opens[i + 1] if i + 1 < len(calendar) else np.nan
        row = {"date": date, "entry_date": entry_date, "entry_open": entry_open}
        for h in horizons:
            target = calendar[i + h] if i + h < len(calendar) else pd.NaT
            price = closes[i + h] if i + h < len(calendar) else np.nan
            row[f"return_{h}"] = price / entry_open - 1
            window = lows[i + 1:i + h + 1] if lows is not None else None
            row[f"mae_{h}"] = (float(window.min()) / entry_open - 1
                              if window is not None and len(window) == h
                              and np.isfinite(window).all() and np.isfinite(entry_open) else np.nan)
            row[f"exit_date_{h}"] = target
        rows.append(row)
    return pd.DataFrame(rows)


def parse_adjustment_events(text: str, code: str) -> pd.DataFrame:
    """Parse JSON only, never execute the provider's JavaScript."""
    try:
        payload = json.loads(text.splitlines()[0].partition("=")[2].strip().rstrip(";"))
        items = payload["data"]
        if len(items) != int(payload["total"]) or not items:
            raise ValueError("incomplete")
        frame = pd.DataFrame(items).rename(columns={"d": "date", "f": "adj_factor"})
        frame["date"] = pd.to_datetime(frame.date, format="%Y-%m-%d")
        frame["adj_factor"] = pd.to_numeric(frame.adj_factor)
        if (frame.date.duplicated().any() or not np.isfinite(frame.adj_factor).all()
                or (frame.adj_factor <= 0).any()):
            raise ValueError("invalid")
        frame["code"] = code
        return frame[["code", "date", "adj_factor"]].sort_values("date").reset_index(drop=True)
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError(f"历史复权事件缺失、格式错误或不完整: {code}") from None


def expand_adjustment_events(daily: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    parts = []
    event_map = {code: group for code, group in events.groupby("code")}
    for code, group in daily.groupby("code", sort=False):
        if code not in event_map:
            raise ValueError(f"股票缺失历史复权事件: {code}")
        history = event_map[code].sort_values("date")
        # An explicit event schedule is piecewise constant; this is not filling
        # missing daily snapshots or inferring unknown corporate actions.
        left = group[["date", "code"]].sort_values("date").copy()
        left["date"] = left.date.astype("datetime64[ns]")
        history["date"] = history.date.astype("datetime64[ns]")
        merged = pd.merge_asof(left, history[["date", "adj_factor"]],
                               on="date", direction="backward")
        parts.append(merged)
    return pd.concat(parts, ignore_index=True)


def load_adjustment_events(codes, cache: Path) -> tuple[pd.DataFrame, list[dict]]:
    directory = cache / "sina_adjustment_events"
    directory.mkdir(parents=True, exist_ok=True)
    local = threading.local()
    lock = threading.Lock()
    last_request = [0.]

    def fetch_one(code):
        target = directory / f"{code}.json"
        symbol = code[-2:].lower() + code[:6]
        url = f"https://finance.sina.com.cn/realstock/company/{symbol}/hfq.js"
        if not target.exists():
            if not hasattr(local, "session"):
                local.session = requests.Session()
                local.session.trust_env = False
            for attempt in range(4):
                with lock:
                    time.sleep(max(0., .08 - (time.monotonic() - last_request[0])))
                    last_request[0] = time.monotonic()
                try:
                    response = local.session.get(url, timeout=20)
                    response.raise_for_status()
                    frame = parse_adjustment_events(response.text, code)
                    payload = {"source": url, "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                               "events": [{"date": str(row.date.date()), "adj_factor": float(row.adj_factor)}
                                          for row in frame.itertuples()]}
                    target.write_text(json.dumps(payload, indent=2) + "\n")
                    break
                except (requests.RequestException, ValueError):
                    if attempt == 3:
                        raise ValueError(f"无法取得完整复权事件: {code}") from None
                    time.sleep(2 ** attempt)
        payload = json.loads(target.read_text())
        frame = pd.DataFrame(payload["events"])
        frame["date"] = pd.to_datetime(frame.date)
        frame["code"] = code
        if (frame.empty or frame.date.duplicated().any() or not np.isfinite(frame.adj_factor).all()
                or (frame.adj_factor <= 0).any()):
            raise ValueError(f"复权缓存无效: {code}")
        return frame, {"code": code, "source": payload["source"], "path": str(target.resolve()),
                       "sha256": sha256(target)}

    parts, audit = [], []
    failures = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = {executor.submit(fetch_one, code): code for code in sorted(set(codes))}
        for i, future in enumerate(as_completed(jobs), 1):
            try:
                frame, record = future.result()
                parts.append(frame)
                audit.append(record)
            except ValueError:
                failures.append(jobs[future])
            if i % 100 == 0 or i == len(jobs):
                print(f"adjustments {i}/{len(jobs)} failures={len(failures)}", flush=True)
    if failures:
        (cache / "missing_adjustment_codes.json").write_text(json.dumps(sorted(failures), indent=2))
        raise ValueError(f"复权事件缺失 {len(failures)}只，见{cache / 'missing_adjustment_codes.json'}；不会降级")
    (cache / "missing_adjustment_codes.json").unlink(missing_ok=True)
    return pd.concat(parts, ignore_index=True), audit


def prepare_data(events: pd.DatetimeIndex, stock_dir: Path = STOCK_DIR,
                 cache: Path = CACHE) -> tuple[pd.DataFrame, pd.DatetimeIndex, list[dict]]:
    paths = sorted(stock_dir.glob("*/*.parquet"))
    calendar = pd.DatetimeIndex([pd.Timestamp(p.stem) for p in paths])
    first, last = calendar.get_indexer([events.min(), events.max()])
    if min(first, last) < 0 or first < 504 or last + 20 >= len(calendar):
        raise ValueError("市场行情未覆盖504日预热或20日收益标签")
    paths = paths[first - 504:last + 21]
    for directory in (cache / "daily",):
        directory.mkdir(parents=True, exist_ok=True)
    daily_parts, audits = [], []
    for index, path in enumerate(paths):
        date = pd.Timestamp(path.stem)
        target = cache / "daily" / path.name
        meta_path = target.with_suffix(".json")
        checksum = sha256(path)
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if (not target.exists() or meta.get("source_sha256") != checksum
                or meta.get("version") != CACHE_VERSION or meta.get("cache_sha256") != sha256(target)):
            raw = pq.read_table(path, columns=["code", "trade_time", "open", "high", "low", "close", "vol"]).to_pandas()
            day = aggregate_day(raw, date)
            day.to_parquet(target, index=False)
            meta = {"version": CACHE_VERSION, "source_path": str(path.resolve()),
                    "source_sha256": checksum, "cache_sha256": sha256(target)}
            meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        cached_day = pd.read_parquet(target)
        day = stock_universe(cached_day)
        daily_parts.append(day)
        audits.append({**meta, "date": path.stem, "rows": len(day), "valid_rows": int(day.valid.sum()),
                       "excluded_cdr_rows": len(cached_day) - len(day)})
        if index % 50 == 0 or index == len(paths) - 1:
            print(f"data {index + 1}/{len(paths)} {date:%Y%m%d} valid={day.valid.sum()}/{len(day)}", flush=True)
    daily = pd.concat(daily_parts, ignore_index=True)
    events, event_audit = load_adjustment_events(daily.loc[daily.valid, "code"].unique(), cache)
    adjustments = expand_adjustment_events(daily.loc[daily.valid], events)
    adjusted = adjust_prices(daily, adjustments)
    audits.extend(event_audit)
    return adjusted, calendar, audits


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="20200101")
    parser.add_argument("--end", default="20251231")
    args = parser.parse_args()
    events = load_events(SOURCE_RUN, args.start, args.end)
    daily, calendar, audit = prepare_data(events)
    daily.to_parquet(CACHE / "prepared.parquet", index=False)
    (CACHE / "preparation_manifest.json").write_text(json.dumps({
        "preparation_version": PREPARATION_VERSION, "prepared_sha256": sha256(CACHE / "prepared.parquet"), "events": [str(d.date()) for d in events],
        "audits": audit}, indent=2) + "\n")
    print(f"prepared {len(daily)} rows; events={len(events)}", flush=True)
