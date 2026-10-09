"""Prepare 2026 H1 intraday inputs without altering the historical source files."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import yaml

from python.run_backtest import ROOT
from python.scoring.data_source import TencentMinuteSource


AMV_PATH = ROOT / "data/backtest_data/0AMV-260612.csv"
LOCAL_STOCK_DIR = ROOT / "data/backtest_data/5m_price/2026"
DIVIDENDS_PATH = ROOT / "python/strategies/amv_winning_defensive/dividends_601288.csv"
DIVIDEND_2026 = {
    "ex_date": "2026-05-13", "cash_per_share": 0.13,
    "source": "https://www.abchina.com/cN/aboutabc/investor_relations/announcements/a-announcement/202605/P020260506662272685289.pdf",
}
FIVE_MINUTE_TIMES = (
    pd.date_range("2000-01-01 09:35", "2000-01-01 11:30", freq="5min").strftime("%H:%M").tolist()
    + pd.date_range("2000-01-01 13:05", "2000-01-01 15:00", freq="5min").strftime("%H:%M").tolist()
)


def validate_session_bars(
    bars: pd.DataFrame, expected_dates: set[pd.Timestamp], code: str, frequency: str,
) -> None:
    if bars.empty:
        raise ValueError(f"{code} 没有 {frequency} 行情")
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.has_duplicates:
        raise ValueError(f"{code} {frequency} 时间戳无效或重复")
    actual_dates = set(bars.index.normalize())
    missing = sorted(expected_dates - actual_dates)
    if missing:
        raise ValueError(f"{code} {frequency} 缺失交易日: {', '.join(str(day.date()) for day in missing)}")
    columns = ("open", "high", "low", "close")
    if not set(columns).issubset(bars.columns) or bars.loc[:, columns].isna().any().any():
        raise ValueError(f"{code} {frequency} 价格列缺失或包含空值")
    if (bars.loc[:, columns] <= 0).any().any():
        raise ValueError(f"{code} {frequency} 包含非正价格")
    for date, day in bars.groupby(bars.index.normalize()):
        if date not in expected_dates:
            continue
        times = day.index.strftime("%H:%M").tolist()
        if frequency == "60m" and times != ["10:30", "11:30", "14:00", "15:00"]:
            raise ValueError(f"{code} {date.date()} 60 分钟行情不完整: {times}")
        if frequency == "5m" and times not in (FIVE_MINUTE_TIMES, ["09:30", *FIVE_MINUTE_TIMES]):
            raise ValueError(f"{code} {date.date()} 5 分钟行情不完整: {len(day)} 根")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _local_bank_day(path: Path) -> pd.DataFrame:
    table = pq.read_table(path, filters=[("code", "==", "601288.SH")],
                          columns=["trade_time", "open", "high", "low", "close", "vol"])
    if not table.num_rows:
        raise ValueError(f"{path} 没有农业银行行情")
    frame = table.to_pandas().rename(columns={"trade_time": "time", "vol": "volume"})
    frame["time"] = pd.to_datetime(frame["time"])
    return frame.set_index("time").sort_index()


def _daily_ohlc(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.groupby(frame.index.normalize()).agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
    )


def prepare_inputs(start: str, end: str, output_dir: Path) -> dict:
    if output_dir.exists():
        manifest_path = output_dir / "source_manifest.json"
        if not manifest_path.is_file():
            raise FileExistsError(f"输入目录已存在且没有来源清单: {output_dir}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("start_date") != start or manifest.get("end_date") != end:
            raise ValueError(f"已有输入快照的日期与请求不一致: {output_dir}")
        for path, checksum in {
            **manifest.get("source_sha256", {}), **manifest.get("generated_sha256", {}),
        }.items():
            if not Path(path).is_file() or _sha256(Path(path)) != checksum:
                raise ValueError(f"已有输入快照文件发生变化: {path}")
        return manifest
    dates = pd.to_datetime(pd.read_csv(AMV_PATH, usecols=["date"])["date"])
    expected = {date.normalize() for date in dates
                if pd.Timestamp(start) <= date <= pd.Timestamp(end)}
    if not expected or max(expected) != pd.Timestamp(end):
        raise ValueError(f"0AMV 没有覆盖请求截止日 {end}")
    local_paths = sorted(LOCAL_STOCK_DIR.glob("*.parquet"))
    local_end = pd.Timestamp(local_paths[-1].stem)
    if local_end >= max(expected):
        raise ValueError("本地农行行情已覆盖请求区间，无需腾讯补数")

    source = TencentMinuteSource()
    etf_bars = {
        code: source.fetch_minute_kline_range(code[:6], start, end, "60m")
        for code in ("512100.SH", "512890.SH")
    }
    for code, frame in etf_bars.items():
        validate_session_bars(frame, expected, code, "60m")

    local_bank_parts = []
    source_files = [AMV_PATH, DIVIDENDS_PATH]
    for date in sorted(day for day in expected if day <= local_end):
        path = LOCAL_STOCK_DIR / f"{date:%Y%m%d}.parquet"
        if not path.is_file():
            raise ValueError(f"本地农业银行行情缺失交易日: {date.date()}")
        local_bank_parts.append(_local_bank_day(path))
        source_files.append(path)
    local_bank = pd.concat(local_bank_parts).sort_index()

    overlap_start = (local_end - pd.Timedelta(days=3)).strftime("%Y%m%d")
    overlap = source.fetch_minute_kline_range("601288", overlap_start,
                                               local_end.strftime("%Y%m%d"), "5m")
    local_daily = _daily_ohlc(local_bank.loc[overlap_start:local_end.strftime("%Y-%m-%d")])
    remote_daily = _daily_ohlc(overlap)
    shared_overlap = local_daily.index.intersection(remote_daily.index)
    if len(shared_overlap) < 2 or (
        (local_daily.loc[shared_overlap] - remote_daily.loc[shared_overlap]).abs() > 0.011
    ).any().any():
        raise ValueError("腾讯与本地农业银行 5 分钟行情在衔接日期的日 OHLC 不一致")

    remote_start = (local_end + pd.Timedelta(days=1)).strftime("%Y%m%d")
    remote_bank = source.fetch_minute_kline_range("601288", remote_start, end, "5m")
    bank = pd.concat([local_bank, remote_bank]).sort_index()
    validate_session_bars(bank, expected, "601288.SH", "5m")

    dividends = pd.read_csv(DIVIDENDS_PATH)
    if DIVIDEND_2026["ex_date"] not in set(dividends["ex_date"]):
        dividends = pd.concat([dividends, pd.DataFrame([DIVIDEND_2026])], ignore_index=True)
    dividends = dividends.sort_values("ex_date")
    if dividends["ex_date"].duplicated().any():
        raise ValueError("农业银行分红数据存在重复除息日")

    output_dir.mkdir(parents=True, exist_ok=False)
    outputs = {}
    for code, frame in etf_bars.items():
        path = output_dir / f"{code}.csv"
        frame.reset_index().rename(columns={"time": "date"}).to_csv(path, index=False)
        outputs[code] = path
    bank_dir = output_dir / "stock_5m"
    (bank_dir / "2026").mkdir(parents=True)
    for date, day in bank.groupby(bank.index.normalize()):
        frame = day.reset_index().rename(columns={"time": "trade_time", "volume": "vol"})
        frame.insert(0, "code", "601288.SH")
        frame.to_parquet(bank_dir / "2026" / f"{date:%Y%m%d}.parquet", index=False)
    dividend_path = output_dir / "dividends_601288.csv"
    dividends.to_csv(dividend_path, index=False)
    config_path = output_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump({"paths": {
        "amv_csv": str(AMV_PATH), "primary_csv": str(outputs["512100.SH"]),
        "defensive_etf_csv": str(outputs["512890.SH"]),
        "stock_5m_dir": str(bank_dir), "stock_dividends_csv": str(dividend_path),
    }}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    generated_files = [*outputs.values(), dividend_path, config_path,
                       *sorted(bank_dir.glob("2026/*.parquet"))]
    manifest = {
        "start_date": start, "end_date": end, "shared_sessions": len(expected),
        "local_bank_end": local_end.strftime("%Y%m%d"),
        "tencent_minute_url": source.MINUTE_KLINE_URL,
        "tencent_pagination": "historical_timestamp_exclusive_320_bars",
        "dividend_2026": DIVIDEND_2026,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_sha256": {str(path): _sha256(path) for path in source_files},
        "generated_sha256": {str(path): _sha256(path) for path in generated_files},
    }
    (output_dir / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="补齐农行防守策略 2026 上半年行情")
    parser.add_argument("--start", default="20260101")
    parser.add_argument("--end", default="20260629")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "data/backtest_data/amv_winning_defensive_2026_h1")
    args = parser.parse_args()
    print(json.dumps(prepare_inputs(args.start, args.end, args.output_dir),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
