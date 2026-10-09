"""Study industry ETF relative-strength divergence versus 510300."""
from __future__ import annotations

from python.research.date_scope import scoped_ranges

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from python.research.amv.ma10_above_ma30_gap.study import generate_buy_signals
from python.factor_research.data import load_amv_csv


ETF_DIR = Path("data/backtest_data/ETF_60min_2005_2025")
REFERENCE_ETF = "510300.SH"
INDUSTRY_ETFS = {
    "512800.SH": ("银行", "银行ETF华宝"),
    "512880.SH": ("证券", "证券ETF国泰"),
    "512200.SH": ("地产", "房地产ETF南方"),
    "159928.SZ": ("消费", "消费ETF"),
    "512010.SH": ("医药", "医药ETF易方达"),
    "512400.SH": ("有色金属", "有色金属ETF南方"),
    "515220.SH": ("煤炭", "煤炭ETF国泰"),
    "515210.SH": ("钢铁", "钢铁ETF国泰"),
    "512660.SH": ("军工", "军工ETF国泰"),
    "512760.SH": ("芯片/半导体", "芯片ETF国泰"),
    "512720.SH": ("计算机", "计算机ETF国泰"),
    "515050.SH": ("通信", "通信ETF华夏"),
    "512980.SH": ("传媒", "传媒ETF广发"),
    "515030.SH": ("新能源车", "新能源车ETF华夏"),
}
LOOKBACKS = (5, 10, 20, 60)
HORIZONS = (3, 5, 10, 20, 30)
SAMPLES = {"train": ("2015-01-01", "2023-12-31"), "oos": ("2024-01-01", "2025-12-31")}
DECILES = tuple(f"Q{index}" for index in range(1, 11))


def aggregate_intraday_etf(raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 60-minute ETF bars into daily OHLCV and amount."""
    aliases = {
        "时间": "date", "日期": "date", "开盘价": "open", "开盘": "open", "最高价": "high", "最高": "high",
        "最低价": "low", "最低": "low", "收盘价": "close", "收盘": "close", "成交量": "volume", "成交额": "amount",
    }
    frame = raw.rename(columns=aliases).copy()
    required = {"date", "open", "high", "low", "close", "volume", "amount"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"ETF 数据缺少列: {', '.join(sorted(missing))}")
    frame = frame.loc[:, ["date", "open", "high", "low", "close", "volume", "amount"]]
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    for column in frame.columns.drop("date"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    daily = frame.sort_values("date").groupby("date", as_index=False, sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), amount=("amount", "sum"),
    )
    if (daily[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("ETF OHLC 必须为正")
    return daily


def build_relative_strength_observations(
    etf: pd.DataFrame,
    benchmark: pd.DataFrame,
    *,
    code: str,
    name: str,
    industry: str,
    lookbacks: Iterable[int] = LOOKBACKS,
) -> pd.DataFrame:
    """Calculate point-in-time industry returns minus 510300 returns."""
    result = etf.loc[:, ["date", "close"]].copy().sort_values("date").reset_index(drop=True)
    reference = benchmark.loc[:, ["date", "close"]].copy().sort_values("date").reset_index(drop=True)
    result = result.rename(columns={"close": "etf_close"})
    reference = reference.rename(columns={"close": "reference_close"})
    for window in (int(value) for value in lookbacks):
        if window <= 0:
            raise ValueError("回看期必须为正整数")
        result[f"etf_return_{window}"] = result["etf_close"] / result["etf_close"].shift(window) - 1.0
        reference[f"reference_return_{window}"] = reference["reference_close"] / reference["reference_close"].shift(window) - 1.0
    result = result.merge(reference, on="date", how="inner")
    for window in (int(value) for value in lookbacks):
        result[f"rs_{window}"] = result[f"etf_return_{window}"] - result[f"reference_return_{window}"]
    result["code"] = code
    result["name"] = name
    result["industry"] = industry
    return result


def _forward_returns(events: pd.DataFrame, prices: pd.DataFrame, horizons: Iterable[int], prefix: str) -> pd.DataFrame:
    dates = prices["date"].to_numpy(dtype="datetime64[ns]")
    event_dates = events["date"].to_numpy(dtype="datetime64[ns]")
    entry_indices = dates.searchsorted(event_dates, side="right")
    output = pd.DataFrame({"date": events["date"].to_numpy()})
    valid = entry_indices < len(prices)
    output["entry_date"] = pd.NaT
    output["entry_open"] = np.nan
    output.loc[valid, "entry_date"] = prices.iloc[entry_indices[valid]]["date"].to_numpy()
    output.loc[valid, "entry_open"] = prices.iloc[entry_indices[valid]]["open"].to_numpy()
    for horizon in (int(value) for value in horizons):
        values = np.full(len(events), np.nan)
        exits = entry_indices + horizon - 1
        available = valid & (exits < len(prices))
        values[available] = (prices.iloc[exits[available]]["close"].to_numpy() / prices.iloc[entry_indices[available]]["open"].to_numpy() - 1.0) * 100.0
        output[f"{prefix}forward_return_{horizon}_pct"] = values
    return output


def attach_forward_returns(
    observations: pd.DataFrame,
    etf: pd.DataFrame,
    benchmark: pd.DataFrame,
    horizons: Iterable[int] = HORIZONS,
) -> pd.DataFrame:
    """Attach tradable ETF returns and same-signal-date 510300 excess returns."""
    horizons = tuple(int(value) for value in horizons)
    events = observations.loc[:, ["date"]].copy()
    etf_labels = _forward_returns(events, etf.loc[:, ["date", "open", "close"]].sort_values("date"), horizons, "")
    reference_labels = _forward_returns(events, benchmark.loc[:, ["date", "open", "close"]].sort_values("date"), horizons, "reference_")
    result = observations.merge(etf_labels, on="date", how="left").merge(
        reference_labels.drop(columns=["entry_date", "entry_open"]), on="date", how="left"
    )
    for horizon in horizons:
        result[f"excess_return_{horizon}_pct"] = result[f"forward_return_{horizon}_pct"] - result[f"reference_forward_return_{horizon}_pct"]
    return result


def assign_cross_section_deciles(observations: pd.DataFrame, factor: str = "rs_20") -> pd.DataFrame:
    """Assign daily equal-count deciles only when at least ten ETFs are available."""
    result = observations.copy()
    result["cross_section_decile"] = pd.Series(pd.NA, index=result.index, dtype="string")
    for _, indices in result.groupby("date", sort=False).groups.items():
        valid = result.loc[indices, factor].dropna()
        if len(valid) < 10 or valid.nunique() < 10:
            continue
        ranks = valid.rank(method="first")
        result.loc[valid.index, "cross_section_decile"] = pd.qcut(ranks, 10, labels=DECILES).astype("string")
    return result


def assign_time_series_deciles(observations: pd.DataFrame, factor: str = "rs_20") -> pd.DataFrame:
    """Assign independent within-ETF deciles for one already-filtered sample stage."""
    result = observations.copy()
    result["time_series_decile"] = pd.Series(pd.NA, index=result.index, dtype="string")
    for _, indices in result.groupby("code", sort=False).groups.items():
        valid = result.loc[indices, factor].dropna()
        if len(valid) < 10 or valid.nunique() < 10:
            continue
        result.loc[valid.index, "time_series_decile"] = pd.qcut(valid.rank(method="first"), 10, labels=DECILES).astype("string")
    return result


def filter_buy_event_observations(
    observations: pd.DataFrame,
    signals: pd.DataFrame,
    signal_types: set[str],
) -> pd.DataFrame:
    """Keep observations whose signal dates carry one of the requested 0AMV buy types."""
    events = signals.loc[signals["signal_type"].isin(signal_types), ["date", "signal_type"]].copy()
    events["date"] = pd.to_datetime(events["date"], errors="raise").dt.normalize()
    if events["date"].duplicated().any():
        raise ValueError("0AMV 买点日期重复")
    result = observations.copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    return result.merge(events, on="date", how="inner")


def select_non_overlapping_events(
    events: pd.DataFrame,
    sessions: Iterable[pd.Timestamp],
    min_gap_sessions: int = 20,
) -> pd.DataFrame:
    """Keep the first event, then require at least ``min_gap_sessions`` ETF sessions.

    Events that do not fall on a reference ETF trading session are excluded because
    their next-session return labels cannot be aligned consistently.
    """
    if min_gap_sessions <= 0:
        raise ValueError("最小间隔必须为正交易日数")
    result = events.copy()
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    session_index = pd.Index(pd.to_datetime(pd.Series(sessions), errors="raise").dt.normalize().drop_duplicates().sort_values())
    positions = session_index.get_indexer(result["date"])
    result = result.assign(_session_position=positions).loc[lambda frame: frame["_session_position"] >= 0]
    kept_positions: list[int] = []
    last_position: int | None = None
    for position in result.sort_values("date")["_session_position"]:
        position = int(position)
        if last_position is None or position - last_position >= min_gap_sessions:
            kept_positions.append(position)
            last_position = position
    return result.loc[result["_session_position"].isin(kept_positions)].drop(columns="_session_position").sort_values("date").reset_index(drop=True)


def classify_industry_behavior(
    effects: pd.DataFrame,
    horizons: Iterable[int] = (5, 10, 20),
) -> pd.DataFrame:
    """Classify per-industry RS20 behavior from its Q10-minus-Q1 spreads.

    Continuation and mean-reversion both require the same sign in at least two
    of the selected horizons; all other industries remain mixed.
    """
    selected = effects.loc[effects["horizon"].isin(tuple(horizons)), ["code", "horizon", "q10_minus_q1_pct"]].copy()
    rows: list[dict] = []
    for code, group in selected.groupby("code", sort=True):
        positive_count = int((group["q10_minus_q1_pct"] > 0).sum())
        negative_count = int((group["q10_minus_q1_pct"] < 0).sum())
        behavior = "continuation" if positive_count >= 2 else "mean_reversion" if negative_count >= 2 else "mixed"
        rows.append({"code": code, "positive_horizon_count": positive_count, "negative_horizon_count": negative_count, "behavior": behavior})
    return pd.DataFrame(rows)


def _summarize_groups(observations: pd.DataFrame, group_column: str, stage: str, scope: str, horizons: Iterable[int]) -> pd.DataFrame:
    rows: list[dict] = []
    for horizon in horizons:
        target, excess = f"forward_return_{horizon}_pct", f"excess_return_{horizon}_pct"
        if scope == "cross_section":
            values = observations.dropna(subset=[group_column, target]).groupby(["date", group_column], observed=True)[[target, excess]].mean().reset_index()
        else:
            values = observations.dropna(subset=[group_column, target]).copy()
        for decile in DECILES:
            group = values.loc[values[group_column] == decile]
            rows.append({
                "scope": scope, "stage": stage, "horizon": horizon, "decile": decile, "sample_count": int(len(group)),
                "mean_return_pct": group[target].mean(), "median_return_pct": group[target].median(),
                "win_rate_pct": (group[target] > 0).mean() * 100.0, "mean_excess_return_pct": group[excess].mean(),
                "median_excess_return_pct": group[excess].median(),
            })
    return pd.DataFrame(rows)


def summarize_cross_section_effects(
    observations: pd.DataFrame,
    stage: str,
    horizons: Iterable[int],
    target_prefix: str = "forward_return",
) -> pd.DataFrame:
    """Summarize top-minus-bottom spread and daily cross-sectional IC."""
    rows: list[dict] = []
    for horizon in horizons:
        target = f"{target_prefix}_{horizon}_pct"
        daily_groups = observations.dropna(subset=["cross_section_decile", target]).groupby(["date", "cross_section_decile"], observed=True)[target].mean().unstack()
        means = daily_groups.mean().reindex(DECILES)
        daily_ic = observations.groupby("date", sort=False).apply(
            lambda frame: frame[["rs_20", target]].dropna().corr(method="spearman").iloc[0, 1]
            if len(frame[["rs_20", target]].dropna()) >= 10 else np.nan,
            include_groups=False,
        ).dropna()
        rows.append({
            "stage": stage, "horizon": horizon, "metric": target_prefix,
            "q10_minus_q1_pct": means.loc["Q10"] - means.loc["Q1"],
            "group_spearman": pd.Series(range(1, 11), index=DECILES, dtype="float64").corr(means.rank(method="average")),
            "strictly_increasing": bool(means.is_monotonic_increasing), "mean_daily_spearman_ic": daily_ic.mean(),
            "positive_ic_rate_pct": (daily_ic > 0).mean() * 100.0, "ic_day_count": int(len(daily_ic)),
        })
    return pd.DataFrame(rows)


def _load_candidate(path: Path, code: str, industry: str, expected_name: str) -> tuple[pd.DataFrame, str]:
    if not path.exists():
        raise FileNotFoundError(f"ETF 数据不存在: {path}")
    raw = pd.read_csv(path, encoding="utf-8-sig")
    if "代码" in raw and not raw["代码"].dropna().astype(str).eq(code).all():
        raise ValueError(f"ETF 文件代码不匹配: {path}")
    name = str(raw["名称"].dropna().iloc[0]) if "名称" in raw and not raw["名称"].dropna().empty else expected_name
    if name != expected_name:
        raise ValueError(f"ETF 文件名称不匹配: {code} 期望 {expected_name}，实际 {name}")
    return aggregate_intraday_etf(raw), name


def _stage_rows(observations: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    result = observations.copy()
    if start is not None:
        result = result.loc[result["date"] >= pd.Timestamp(start)]
    if end is not None:
        result = result.loc[result["date"] <= pd.Timestamp(end)]
    return result.reset_index(drop=True)


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    rows = frame.fillna("").astype(str).itertuples(index=False, name=None)
    return "\n".join([
        "| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ])


def run_research(
    etf_dir: Path,
    output_dir: Path,
    event_signals: pd.DataFrame | None = None,
    event_description: str = "全部交易日",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run RS20 cross-sectional and per-ETF time-series research."""
    reference = aggregate_intraday_etf(pd.read_csv(etf_dir / f"{REFERENCE_ETF}.csv", encoding="utf-8-sig"))
    all_rows: list[pd.DataFrame] = []
    coverage: list[dict] = []
    for code, (industry, expected_name) in INDUSTRY_ETFS.items():
        daily, name = _load_candidate(etf_dir / f"{code}.csv", code, industry, expected_name)
        factors = build_relative_strength_observations(daily, reference, code=code, name=name, industry=industry)
        rows = attach_forward_returns(factors, daily, reference)
        all_rows.append(rows)
        coverage.append({"code": code, "name": name, "industry": industry, "daily_start": daily["date"].min(), "daily_end": daily["date"].max(), "observation_count": len(rows)})
    observations = pd.concat(all_rows, ignore_index=True)
    if event_signals is not None:
        observations = filter_buy_event_observations(observations, event_signals, set(event_signals["signal_type"].unique()))
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[pd.DataFrame] = []
    effect_rows: list[pd.DataFrame] = []
    time_rows: list[pd.DataFrame] = []
    eligible_dates: list[pd.DataFrame] = []
    for stage, (start, end) in scoped_ranges(SAMPLES, include_all=True).items():
        stage_rows = _stage_rows(observations, start, end)
        cross_rows = assign_cross_section_deciles(stage_rows)
        timed_rows = assign_time_series_deciles(stage_rows)
        cross_rows.to_csv(output_dir / f"daily_cross_section_observations_{stage}.csv", index=False, encoding="utf-8-sig")
        timed_rows.to_csv(output_dir / f"time_series_observations_{stage}.csv", index=False, encoding="utf-8-sig")
        summary_rows.append(_summarize_groups(cross_rows, "cross_section_decile", stage, "cross_section", HORIZONS))
        effect_rows.append(summarize_cross_section_effects(cross_rows, stage, HORIZONS))
        for code, etf_rows in timed_rows.groupby("code", sort=True):
            time_rows.append(
                _summarize_groups(etf_rows, "time_series_decile", stage, "time_series", HORIZONS).assign(
                    code=code,
                    name=etf_rows["name"].iloc[0],
                    industry=etf_rows["industry"].iloc[0],
                )
            )
        count = stage_rows.groupby("date")["code"].nunique().rename("available_etf_count").reset_index()
        count["stage"] = stage
        count["eligible_for_deciles"] = count["available_etf_count"] >= 10
        eligible_dates.append(count)
    summary = pd.concat(summary_rows, ignore_index=True)
    effects = pd.concat(effect_rows, ignore_index=True)
    time_summary = pd.concat(time_rows, ignore_index=True)
    coverage_frame = pd.DataFrame(coverage)
    daily_coverage = pd.concat(eligible_dates, ignore_index=True)
    coverage_by_stage = daily_coverage.groupby("stage", as_index=False).agg(
        eligible_date_count=("eligible_for_deciles", "sum"),
        total_signal_date_count=("date", "count"),
    )
    coverage_by_stage["excluded_date_count"] = (
        coverage_by_stage["total_signal_date_count"] - coverage_by_stage["eligible_date_count"]
    )
    coverage_frame.to_csv(output_dir / "coverage.csv", index=False, encoding="utf-8-sig")
    daily_coverage.to_csv(output_dir / "daily_coverage.csv", index=False, encoding="utf-8-sig")
    coverage_by_stage.to_csv(output_dir / "coverage_by_stage.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(output_dir / "cross_section_summary.csv", index=False, encoding="utf-8-sig")
    effects.to_csv(output_dir / "cross_section_effects.csv", index=False, encoding="utf-8-sig")
    time_summary.to_csv(output_dir / "time_series_summary.csv", index=False, encoding="utf-8-sig")
    metadata = {"reference": REFERENCE_ETF, "candidates": INDUSTRY_ETFS, "lookbacks": LOOKBACKS, "horizons": HORIZONS, "samples": SAMPLES, "entry": "next ETF session open", "factor": "RS20 = ETF 20-day return - 510300 20-day return", "event_sample": event_description}
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    report = "# 行业ETF相对510300收益率背离研究\n\n主因子：RS20。样本：" + event_description + "。截面统计对每个日期的分组收益等权后再跨日汇总。\n\n## 截面十组统计\n\n" + _markdown_table(summary.round(3)) + "\n\n## 截面效应与IC\n\n" + _markdown_table(effects.round(3)) + "\n\n## 覆盖率\n\n" + _markdown_table(coverage_frame) + "\n"
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return summary, effects, time_summary


def run_buy_event_research(amv_path: Path, etf_dir: Path, output_root: Path) -> pd.DataFrame:
    """Run the RS20 study separately for class-2, class-3, and combined 0AMV buy events."""
    signals = generate_buy_signals(load_amv_csv(amv_path))
    scenarios = {
        "class_2": {"class_2"},
        "class_3": {"class_3"},
        "class_2_3_combined": {"class_2", "class_3"},
    }
    effects: list[pd.DataFrame] = []
    for scenario, signal_types in scenarios.items():
        event_signals = signals.loc[signals["signal_type"].isin(signal_types)].copy()
        _, scenario_effects, _ = run_research(
            etf_dir,
            output_root / scenario,
            event_signals=event_signals,
            event_description=f"0AMV {' + '.join(sorted(signal_types))} 买点日",
        )
        effects.append(scenario_effects.assign(scenario=scenario))
    combined = pd.concat(effects, ignore_index=True)
    output_root.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_root / "scenario_effects.csv", index=False, encoding="utf-8-sig")
    return combined


def _leave_one_out_effects(observations: pd.DataFrame, excluded_column: str) -> pd.DataFrame:
    """Recompute all-sample cross-sectional spreads after excluding one event or ETF."""
    rows: list[pd.DataFrame] = []
    for excluded_value in sorted(observations[excluded_column].dropna().unique()):
        reduced = observations.loc[observations[excluded_column] != excluded_value]
        deciles = assign_cross_section_deciles(reduced)
        for metric in ("forward_return", "excess_return"):
            result = summarize_cross_section_effects(deciles, "all", (5, 10, 20), metric)
            result["excluded_column"] = excluded_column
            result["excluded_value"] = excluded_value
            rows.append(result)
    return pd.concat(rows, ignore_index=True)


def _time_series_spreads(time_summary: pd.DataFrame, stage: str) -> pd.DataFrame:
    """Convert per-ETF decile summaries into Q10-minus-Q1 spreads."""
    selected = time_summary.loc[time_summary["stage"] == stage]
    pivot = selected.pivot_table(
        index=["code", "name", "industry", "horizon"], columns="decile", values="mean_return_pct", aggfunc="first"
    ).reset_index()
    pivot["q10_minus_q1_pct"] = pivot["Q10"] - pivot["Q1"]
    return pivot


def run_class_3_deep_dive(amv_path: Path, etf_dir: Path, output_dir: Path) -> None:
    """Stress-test RS20 specifically on class-3 0AMV buy-event dates."""
    signals = generate_buy_signals(load_amv_csv(amv_path))
    class_3 = signals.loc[signals["signal_type"] == "class_3"].copy()
    reference = aggregate_intraday_etf(pd.read_csv(etf_dir / f"{REFERENCE_ETF}.csv", encoding="utf-8-sig"))
    non_overlapping = select_non_overlapping_events(class_3, reference["date"], min_gap_sessions=20)
    output_dir.mkdir(parents=True, exist_ok=True)

    overlapping_dir = output_dir / "overlapping"
    overlapping_summary, overlapping_effects, overlapping_time = run_research(
        etf_dir, overlapping_dir, event_signals=class_3, event_description="0AMV 三类买点日（允许事件重叠）"
    )
    non_overlapping_dir = output_dir / "non_overlapping_20_sessions"
    _, non_overlapping_effects, _ = run_research(
        etf_dir, non_overlapping_dir, event_signals=non_overlapping,
        event_description="0AMV 三类买点日（相邻保留事件至少间隔20个510300交易日）",
    )

    observations = pd.read_csv(overlapping_dir / "daily_cross_section_observations_all.csv", encoding="utf-8-sig", parse_dates=["date"])
    non_overlapping_observations = pd.read_csv(
        non_overlapping_dir / "daily_cross_section_observations_all.csv", encoding="utf-8-sig", parse_dates=["date"]
    )
    leave_one_event = _leave_one_out_effects(observations, "date")
    leave_one_industry = _leave_one_out_effects(observations, "code")
    leave_one_event.to_csv(output_dir / "leave_one_event_effects.csv", index=False, encoding="utf-8-sig")
    leave_one_industry.to_csv(output_dir / "leave_one_industry_effects.csv", index=False, encoding="utf-8-sig")

    train_spreads = _time_series_spreads(overlapping_time, "train")
    behaviors = classify_industry_behavior(train_spreads)
    identity = train_spreads[["code", "name", "industry"]].drop_duplicates()
    behaviors = identity.merge(behaviors, on="code", how="left").sort_values("code")
    behaviors.to_csv(output_dir / "industry_behavior_groups_from_train.csv", index=False, encoding="utf-8-sig")

    metric_effects = pd.concat(
        [
            overlapping_effects.assign(sample_scheme="overlapping"),
            summarize_cross_section_effects(observations, "all", HORIZONS, "excess_return").assign(sample_scheme="overlapping"),
            non_overlapping_effects.assign(sample_scheme="non_overlapping_20_sessions"),
            summarize_cross_section_effects(
                non_overlapping_observations, "all", HORIZONS, "excess_return"
            ).assign(sample_scheme="non_overlapping_20_sessions"),
        ],
        ignore_index=True,
    )
    metric_effects.to_csv(output_dir / "sample_scheme_effects.csv", index=False, encoding="utf-8-sig")
    train_behavior_spreads = train_spreads.loc[train_spreads["horizon"].isin((5, 10, 20))].merge(
        behaviors[["code", "behavior"]], on="code", how="left"
    )
    train_behavior_spreads.to_csv(output_dir / "industry_train_spreads.csv", index=False, encoding="utf-8-sig")

    stability = leave_one_event.loc[(leave_one_event["metric"] == "forward_return") & (leave_one_event["horizon"].isin((5, 10, 20)))].groupby("horizon", as_index=False).agg(
        min_q10_minus_q1_pct=("q10_minus_q1_pct", "min"), max_q10_minus_q1_pct=("q10_minus_q1_pct", "max")
    )
    industry_stability = leave_one_industry.loc[(leave_one_industry["metric"] == "forward_return") & (leave_one_industry["horizon"].isin((5, 10, 20)))].groupby("horizon", as_index=False).agg(
        min_q10_minus_q1_pct=("q10_minus_q1_pct", "min"), max_q10_minus_q1_pct=("q10_minus_q1_pct", "max")
    )
    report = """# 0AMV 三类买点的 RS20 深度稳健性研究

本研究仅使用三类买点日。RS20 = 行业 ETF 过去20个交易日收益率 − 510300同期收益率；收益从信号后下一交易日开盘进入。所有结论为样本研究，不构成交易建议。

## 读取顺序

先比较 `sample_scheme_effects.csv` 的重叠与20交易日非重叠事件样本；再检查留一结果的最小值是否仍为正。`industry_behavior_groups_from_train.csv` 的行业标签只由 TRAIN（2015--2023）形成，避免把 OOS 收益用于分类。

## 样本方案效应

""" + _markdown_table(metric_effects.round(3)) + "\n\n## 留一事件后的绝对收益 Q10-Q1 范围\n\n" + _markdown_table(stability.round(3)) + "\n\n## 留一行业后的绝对收益 Q10-Q1 范围\n\n" + _markdown_table(industry_stability.round(3)) + "\n\n## TRAIN 形成的行业行为标签\n\n" + _markdown_table(behaviors) + "\n\n训练期行业标签只是后续二阶段筛选的候选条件；由于三类买点 OOS 只有很少事件，不能将其视作已验证的实盘规则。\n"
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps({
        "event_type": "class_3", "non_overlapping_gap_sessions": 20,
        "behavior_training_period": SAMPLES["train"], "behavior_horizons": [5, 10, 20],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--etf-dir", type=Path, default=ETF_DIR)
    parser.add_argument("--output", type=Path, default=Path("data/factor_research_runs/industry_etf_rs20"))
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--buy-events", action="store_true", help="只研究0AMV二类、三类买点日")
    parser.add_argument("--class-3-deep-dive", action="store_true", help="对0AMV三类买点执行RS20稳健性研究")
    args = parser.parse_args()
    if args.class_3_deep_dive:
        run_class_3_deep_dive(args.amv, args.etf_dir, args.output)
        print(f"已输出三类买点RS20稳健性报告: {args.output / 'report.md'}")
    elif args.buy_events:
        print(run_buy_event_research(args.amv, args.etf_dir, args.output).to_string(index=False))
    else:
        summary, effects, _ = run_research(args.etf_dir, args.output)
        print(summary.to_string(index=False))
        print(effects.to_string(index=False))


if __name__ == "__main__":
    main()
