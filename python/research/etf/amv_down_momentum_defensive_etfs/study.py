"""0AMV MACD death crosses and subsequent dividend/coal ETF total returns."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from python.factor_research.data import load_amv_csv
from python.research.date_scope import scoped_ranges
from python.strategies.amv_winning.runner import CONSOLIDATION_DATE, CONSOLIDATION_RATIO, generate_amv_signals
from python.strategies.amv_winning_rotation.runner import COAL_SPLIT_EX_DATE, COAL_SPLIT_RATIO, DIVIDEND_EVENTS


CODES = ("510880.SH", "515220.SH", "512100.SH")
HORIZONS = (1, 3, 5, 10, 20)
SAMPLES = {"train": ("2020-03-02", "2023-12-31"), "oos": ("2024-01-01", "2025-12-31")}
SEVERE_THRESHOLD = -0.04
# The 512100 cash distribution is included in the benchmark's total return.
BENCHMARK_DIVIDEND = ("512100.SH", "2025-01-14", "2025-01-15", "2025-01-20", 0.037)


def format_report(summary: pd.DataFrame, metadata: dict) -> str:
    return (
        "# 0AMV 下跌动量与防守 ETF 远期收益\n\n"
        f"事件数：{metadata['event_count']}。入场口径：{metadata['entry']}。"
        "下表保留全部分组与预测期的汇总结果；未来收益用于研究标签，不代表可直接取得的策略收益。\n\n"
        "## 全部分组汇总\n\n"
        + summary.to_markdown(index=False) + "\n"
    )


def build_events(amv: pd.DataFrame) -> pd.DataFrame:
    signals = generate_amv_signals(amv)
    signals["momentum_3"] = signals["close"].pct_change(3)
    signals["ma30"] = signals["close"].rolling(30).mean()
    events = signals.loc[signals["exit_macd"] & signals["momentum_3"].notna(),
                         ["date", "close", "momentum_3", "ma10", "ma30"]].copy()
    events["severe_drop"] = events["momentum_3"] <= SEVERE_THRESHOLD
    events["ma10_below_ma30"] = events["ma10"] < events["ma30"]
    return events.reset_index(drop=True)


def daily_prices(raw: pd.DataFrame) -> pd.DataFrame:
    aliases = {"时间": "date", "开盘价": "open", "收盘价": "close", "成交量": "volume"}
    frame = raw.rename(columns=aliases).copy()
    required = {"date", "open", "close", "volume"}
    if not required.issubset(frame):
        raise ValueError(f"ETF 数据缺少列: {sorted(required - set(frame))}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    for col in ("open", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    if frame["date"].duplicated().any() or (frame[["open", "close"]] <= 0).any().any():
        raise ValueError("ETF 数据存在重复时间或非正价格")
    frame = frame.sort_values("date")
    daily = frame.groupby(frame["date"].dt.normalize(), sort=True).agg(
        open=("open", "first"), close=("close", "last"), volume=("volume", "sum")
    ).reset_index()
    return daily.loc[daily["volume"] > 0, ["date", "open", "close"]].reset_index(drop=True)


def total_return(
    code: str, entry_date: pd.Timestamp, exit_date: pd.Timestamp, entry_open: float, exit_close: float,
    *, dividend_events: Iterable[tuple] = (*DIVIDEND_EVENTS, BENCHMARK_DIVIDEND),
) -> float:
    """Gross per-share wealth return, including units after splits and earned cash."""
    units = 1.0
    splits = {"515220.SH": (COAL_SPLIT_EX_DATE, COAL_SPLIT_RATIO),
              "512100.SH": (CONSOLIDATION_DATE, CONSOLIDATION_RATIO)}
    split = splits.get(code)
    if split and entry_date < split[0] <= exit_date:
        units *= split[1]
    cash = 0.0
    for event_code, record, ex_date, _pay_date, amount in dividend_events:
        record, ex_date = pd.Timestamp(record), pd.Timestamp(ex_date)
        if event_code == code and entry_date <= record < ex_date <= exit_date:
            units_on_record = split[1] if split and entry_date < split[0] <= record else 1.0
            cash += amount * units_on_record
    return (units * exit_close + cash) / entry_open - 1.0


def label_events(events: pd.DataFrame, daily_by_code: dict[str, pd.DataFrame],
                 horizons: Iterable[int] = HORIZONS) -> pd.DataFrame:
    horizons = tuple(horizons)
    if not horizons or any(h <= 0 for h in horizons) or set(daily_by_code) != set(CODES):
        raise ValueError("需要三只 ETF 的日线和正整数远期周期")
    frames = {}
    for code, frame in daily_by_code.items():
        prices = frame.copy()
        prices["date"] = pd.to_datetime(prices["date"]).dt.normalize()
        if prices["date"].duplicated().any() or (prices[["open", "close"]] <= 0).any().any():
            raise ValueError(f"{code} 日线存在重复日期或非正价格")
        frames[code] = prices.set_index("date").sort_index()
    common = sorted(set.intersection(*(set(frame.index) for frame in frames.values())))
    if not common:
        raise ValueError("三只 ETF 没有共同交易日")
    calendar = pd.DatetimeIndex(common)
    result = events.copy().reset_index(drop=True)
    result["date"] = pd.to_datetime(result["date"]).dt.normalize()
    records = []
    for event in result.itertuples(index=False):
        index = calendar.searchsorted(event.date, side="right")
        row = {"entry_date": pd.NaT}
        if index < len(calendar):
            entry = calendar[index]
            row["entry_date"] = entry
            for horizon in horizons:
                exit_index = index + horizon - 1
                row[f"exit_date_{horizon}d"] = calendar[exit_index] if exit_index < len(calendar) else pd.NaT
                for code in CODES:
                    row[f"{code}_return_{horizon}d_pct"] = (
                        total_return(code, entry, calendar[exit_index],
                                     frames[code].at[entry, "open"], frames[code].at[calendar[exit_index], "close"]) * 100
                        if exit_index < len(calendar) else np.nan
                    )
                for code in CODES[:2]:
                    row[f"{code}_excess_{horizon}d_pct"] = (
                        row[f"{code}_return_{horizon}d_pct"] - row[f"512100.SH_return_{horizon}d_pct"]
                    )
        records.append(row)
    return pd.concat([result, pd.DataFrame(records)], axis=1)


def summarize(observations: pd.DataFrame, horizons: Iterable[int] = HORIZONS) -> pd.DataFrame:
    rows = []
    groups = {
        "all": pd.Series(True, index=observations.index),
        "severe": observations["severe_drop"],
        "other": ~observations["severe_drop"],
        "ma10_below_ma30": observations["ma10_below_ma30"],
        "severe_and_ma_down": observations["severe_drop"] & observations["ma10_below_ma30"],
    }
    for stage in ("train", "oos", "all"):
        stage_rows = observations if stage == "all" else observations.loc[observations["stage"] == stage]
        for group, mask in groups.items():
            sample = stage_rows.loc[mask.reindex(stage_rows.index, fill_value=False)]
            for code in CODES[:2]:
                for horizon in horizons:
                    values = sample[f"{code}_return_{horizon}d_pct"].dropna()
                    excess = sample[f"{code}_excess_{horizon}d_pct"].dropna()
                    valid = sample.loc[values.index]
                    rows.append({
                        "stage": stage, "group": group, "code": code, "horizon": horizon,
                        "events": len(sample), "labeled": len(values), "missing_labels": len(sample)-len(values),
                        "mean_pct": values.mean(), "median_pct": values.median(),
                        "win_rate_pct": (values > 0).mean()*100 if len(values) else np.nan,
                        "p10_pct": values.quantile(0.1), "mean_excess_pct": excess.mean(),
                        "spearman_momentum_return": valid["momentum_3"].rank().corr(values.rank()) if len(values) >= 3 else np.nan,
                    })
    return pd.DataFrame(rows)


def run_research(amv_path: Path, etf_dir: Path, output_dir: Path,
                 horizons: Iterable[int] = HORIZONS) -> tuple[pd.DataFrame, pd.DataFrame]:
    horizons = tuple(horizons)
    events = build_events(load_amv_csv(amv_path))
    prices = {code: daily_prices(pd.read_csv(etf_dir / f"{code}.csv")) for code in CODES}
    observations = label_events(events, prices, horizons)
    ranges = scoped_ranges(SAMPLES, include_all=True)
    allowed = ranges.get("all")
    if allowed is not None:
        allowed = (max(pd.Timestamp(allowed[0]) if allowed[0] else pd.Timestamp(SAMPLES["train"][0]),
                   pd.Timestamp(SAMPLES["train"][0])),
                   min(pd.Timestamp(allowed[1]) if allowed[1] else pd.Timestamp(SAMPLES["oos"][1]),
                       pd.Timestamp(SAMPLES["oos"][1])))
    if allowed is None:
        observations = observations.iloc[0:0].copy()
    else:
        observations = observations.loc[observations["date"].between(*map(pd.Timestamp, allowed))].copy()
    observations["stage"] = np.where(observations["date"] <= pd.Timestamp(SAMPLES["train"][1]), "train", "oos")
    observations = observations.reset_index(drop=True)
    summary = summarize(observations, horizons)
    output_dir.mkdir(parents=True, exist_ok=True)
    observations.to_csv(output_dir / "observations.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "factor": "0AMV close(t)/close(t-3)-1 on MACD death crosses",
        "severe_threshold": SEVERE_THRESHOLD, "samples": SAMPLES, "horizons": list(horizons),
        "entry": "next common ETF session open", "exit": "Nth common ETF session close",
        "return": "gross total return, cash dividends and splits included; no fees",
        "benchmark": "512100.SH total return", "data_sources": [str(amv_path), *(str(etf_dir / f"{c}.csv") for c in CODES)],
        "event_count": len(observations), "missing_entry_count": int(observations["entry_date"].isna().sum()),
        "missing_labels_by_horizon": {
            str(horizon): int(observations[f"510880.SH_return_{horizon}d_pct"].isna().sum())
            for horizon in horizons
        },
        "overlapping_consecutive_events_by_horizon": {
            str(horizon): int((observations["entry_date"].iloc[1:].reset_index(drop=True)
                               <= observations[f"exit_date_{horizon}d"].iloc[:-1].reset_index(drop=True)).sum())
            for horizon in horizons
        },
        "overlap_note": "Forward windows may overlap; events are not independent trades.",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(format_report(summary, metadata), encoding="utf-8")
    return observations, summary
