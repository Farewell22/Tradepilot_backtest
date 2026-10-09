"""Cross-sectional ETF study at class-2/class-3 0AMV buy events."""
from __future__ import annotations

from python.research.date_scope import scoped_ranges

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from python.research.etf.etf_kdj_rotation.study import CANDIDATES, ETF_DIR, REFERENCE_ETF
from python.research.amv.ma10_above_ma30_gap.study import generate_buy_signals
from python.factor_research.data import load_amv_csv


HORIZONS = (3, 5, 10, 20)
SAMPLES = {"train": ("2015-01-01", "2023-12-31"), "oos": ("2024-01-01", "2025-12-31")}
FLOW_LOOKBACK = 7
FLOW_BASELINE = 20
MIN_CROSS_SECTION = 5


def aggregate_intraday_etf(raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate source 60-minute ETF bars to daily OHLC, volume, and amount."""
    aliases = {
        "时间": "date", "日期": "date", "开盘价": "open", "开盘": "open",
        "最高价": "high", "最高": "high", "最低价": "low", "最低": "low",
        "收盘价": "close", "收盘": "close", "成交量": "volume", "成交额": "amount",
    }
    frame = raw.rename(columns=aliases).copy()
    required = {"date", "open", "high", "low", "close", "volume", "amount"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"ETF 数据缺少列: {', '.join(sorted(missing))}")
    frame = frame.loc[:, ["date", "open", "high", "low", "close", "volume", "amount"]]
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    for column in ("open", "high", "low", "close", "volume", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    return frame.sort_values("date").groupby("date", as_index=False, sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), amount=("amount", "sum"),
    )


def add_flow_trend_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Add point-in-time 7-versus-prior-20 flow and MA trend features."""
    result = daily.copy().sort_values("date").reset_index(drop=True)
    for column in ("close", "volume", "amount"):
        result[column] = pd.to_numeric(result[column], errors="raise")
    for metric in ("amount", "volume"):
        recent = result[metric].rolling(FLOW_LOOKBACK, min_periods=FLOW_LOOKBACK).mean()
        prior = result[metric].shift(FLOW_LOOKBACK).rolling(FLOW_BASELINE, min_periods=FLOW_BASELINE).mean()
        result[f"{metric}_ratio_7_20"] = recent / prior
        result[f"{metric}_sum_7"] = result[metric].rolling(FLOW_LOOKBACK, min_periods=FLOW_LOOKBACK).sum()
    result["ma10"] = result["close"].rolling(10, min_periods=10).mean()
    result["ma30"] = result["close"].rolling(30, min_periods=30).mean()
    result["ma10_above_ma30"] = result["ma10"] > result["ma30"]
    result["ma10_slope_5d"] = result["ma10"] / result["ma10"].shift(5) - 1.0
    return result


def attach_forward_returns(events: pd.DataFrame, daily: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """Attach next-session-open to Nth-session-close tradable returns."""
    prices = daily.loc[:, ["date", "open", "close"]].copy().sort_values("date").reset_index(drop=True)
    events = events.copy()
    events["date"] = pd.to_datetime(events["date"], errors="raise").dt.normalize()
    values = prices["date"].to_numpy(dtype="datetime64[ns]")
    entry_index = values.searchsorted(events["date"].to_numpy(dtype="datetime64[ns]"), side="right")
    valid = entry_index < len(prices)
    result = events.loc[valid].copy().reset_index(drop=True)
    entry_index = entry_index[valid]
    result["entry_date"] = prices.iloc[entry_index]["date"].to_numpy()
    result["entry_open"] = prices.iloc[entry_index]["open"].to_numpy()
    for horizon in horizons:
        exit_index = entry_index + int(horizon) - 1
        column = f"forward_return_{horizon}_pct"
        result[column] = np.nan
        available = exit_index < len(prices)
        result.loc[available, column] = (
            prices.iloc[exit_index[available]]["close"].to_numpy() / result.loc[available, "entry_open"].to_numpy() - 1.0
        ) * 100.0
    return result


def _event_quintiles(rows: pd.DataFrame, factor: str) -> pd.Series:
    valid = rows[factor].notna()
    output = pd.Series(pd.NA, index=rows.index, dtype="string")
    if valid.sum() < MIN_CROSS_SECTION or rows.loc[valid, factor].nunique() < MIN_CROSS_SECTION:
        return output
    ranks = rows.loc[valid, factor].rank(method="first")
    output.loc[valid] = pd.qcut(ranks, 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"]).astype("string")
    return output


def _load_universe(etf_dir: Path) -> dict[str, pd.DataFrame]:
    daily: dict[str, pd.DataFrame] = {}
    for code in CANDIDATES:
        path = etf_dir / f"{code}.csv"
        if not path.exists():
            raise FileNotFoundError(f"ETF 数据不存在: {path}")
        daily[code] = add_flow_trend_features(aggregate_intraday_etf(pd.read_csv(path)))
    return daily


def build_observations(events: pd.DataFrame, universe: dict[str, pd.DataFrame], reference: pd.DataFrame, common_only: bool) -> pd.DataFrame:
    """Build one ETF observation per event date, with factors known at that close."""
    common_start = max(frame["date"].min() for frame in universe.values())
    reference_labels = attach_forward_returns(events[["date"]], reference)
    reference_labels = reference_labels.set_index("date")
    rows: list[pd.DataFrame] = []
    for code, daily in universe.items():
        factor_rows = daily.copy()
        factor_rows["code"] = code
        factor_rows["name"] = CANDIDATES[code]
        merged = events[["date", "signal_type"]].merge(factor_rows, on="date", how="left")
        if common_only:
            merged = merged.loc[merged["date"] >= common_start]
        merged = merged.loc[merged["close"].notna()].copy()
        labels = attach_forward_returns(merged[["date"]], daily)
        label_columns = ["date", "entry_date", "entry_open"] + [f"forward_return_{h}_pct" for h in HORIZONS]
        merged = merged.merge(labels[label_columns], on="date", how="left", suffixes=("", "_label"))
        for horizon in HORIZONS:
            reference_column = f"reference_forward_return_{horizon}_pct"
            merged[reference_column] = merged["date"].map(reference_labels[f"forward_return_{horizon}_pct"])
            merged[f"excess_return_{horizon}_pct"] = merged[f"forward_return_{horizon}_pct"] - merged[reference_column]
        rows.append(merged)
    observations = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if observations.empty:
        return observations
    observations["amount_7_share"] = observations.groupby("date")["amount_sum_7"].transform(lambda value: value / value.sum())
    for factor in ("amount_ratio_7_20", "volume_ratio_7_20", "amount_7_share", "ma10_slope_5d"):
        observations[f"{factor}_quintile"] = observations.groupby("date", group_keys=False).apply(
            lambda frame: _event_quintiles(frame, factor), include_groups=False
        )
    return observations


def summarize_factor(observations: pd.DataFrame, factor: str, universe_name: str, stage: str) -> pd.DataFrame:
    rows: list[dict] = []
    quintile_column = f"{factor}_quintile"
    for horizon in HORIZONS:
        target = f"forward_return_{horizon}_pct"
        excess = f"excess_return_{horizon}_pct"
        event_groups = observations.dropna(subset=[quintile_column, target]).groupby(["date", quintile_column], observed=True)[[target, excess]].mean()
        for quintile in ("Q1", "Q2", "Q3", "Q4", "Q5"):
            values = event_groups.xs(quintile, level=1, drop_level=False) if quintile in event_groups.index.get_level_values(1) else pd.DataFrame()
            rows.append({
                "universe": universe_name, "stage": stage, "factor": factor, "horizon": horizon, "quintile": quintile,
                "event_count": int(len(values)), "mean_return_pct": values[target].mean() if not values.empty else np.nan,
                "mean_excess_return_pct": values[excess].mean() if not values.empty else np.nan,
                "win_rate_pct": (values[target] > 0).mean() * 100 if not values.empty else np.nan,
            })
        ics = observations.groupby("date").apply(
            lambda frame: frame[[factor, target]].dropna().corr(method="spearman").iloc[0, 1] if len(frame[[factor, target]].dropna()) >= MIN_CROSS_SECTION else np.nan,
            include_groups=False,
        ).dropna()
        top = observations.dropna(subset=[factor, target]).sort_values(["date", factor, "code"], ascending=[True, False, True]).groupby("date", as_index=False).first()
        rows.append({
            "universe": universe_name, "stage": stage, "factor": factor, "horizon": horizon, "quintile": "IC/top1",
            "event_count": int(len(ics)), "mean_return_pct": top[target].mean(), "mean_excess_return_pct": top[excess].mean(),
            "win_rate_pct": (top[target] > 0).mean() * 100, "mean_spearman_ic": ics.mean(), "positive_ic_rate_pct": (ics > 0).mean() * 100,
        })
    return pd.DataFrame(rows)


def _markdown_table(frame: pd.DataFrame) -> str:
    """Render a small DataFrame without requiring pandas' optional tabulate dependency."""
    columns = list(frame.columns)
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    values = frame.fillna("").astype(str)
    body = ["| " + " | ".join(row) + " |" for row in values.itertuples(index=False, name=None)]
    return "\n".join([header, divider, *body])


def summarize_regimes(observations: pd.DataFrame, universe_name: str, stage: str) -> pd.DataFrame:
    """Measure the MA10 trend filter and its interaction with the primary flow factor."""
    rows: list[dict] = []
    trend_up = observations["ma10_above_ma30"].eq(True)
    regimes = {
        "ma10_above_ma30": trend_up,
        "ma10_not_above_ma30": ~trend_up,
        "low_amount_ratio_q1_and_ma10_up": (
            observations["amount_ratio_7_20_quintile"].eq("Q1") & trend_up
        ),
        "high_amount_ratio_q5_and_ma10_up": (
            observations["amount_ratio_7_20_quintile"].eq("Q5") & trend_up
        ),
    }
    for horizon in HORIZONS:
        target = f"forward_return_{horizon}_pct"
        excess = f"excess_return_{horizon}_pct"
        for regime, mask in regimes.items():
            values = observations.loc[mask].dropna(subset=[target]).groupby("date")[[target, excess]].mean()
            rows.append({
                "universe": universe_name, "stage": stage, "regime": regime, "horizon": horizon,
                "event_count": int(len(values)), "mean_return_pct": values[target].mean(),
                "mean_excess_return_pct": values[excess].mean(),
                "win_rate_pct": (values[target] > 0).mean() * 100,
            })
    return pd.DataFrame(rows)


def run_research(amv_path: Path, etf_dir: Path, reference_path: Path, output_dir: Path) -> pd.DataFrame:
    amv = load_amv_csv(amv_path)
    events = generate_buy_signals(amv).loc[lambda frame: frame["signal_type"].isin(["class_2", "class_3"]), ["date", "signal_type"]]
    universe = _load_universe(etf_dir)
    reference = aggregate_intraday_etf(pd.read_csv(reference_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[pd.DataFrame] = []
    regime_summaries: list[pd.DataFrame] = []
    for universe_name, common_only in (("common_universe", True), ("dynamic_universe", False)):
        observations = build_observations(events, universe, reference, common_only)
        for stage, bounds in scoped_ranges(SAMPLES, include_all=True).items():
            stage_rows = observations.copy()
            if bounds[0]: stage_rows = stage_rows.loc[stage_rows["date"] >= pd.Timestamp(bounds[0])]
            if bounds[1]: stage_rows = stage_rows.loc[stage_rows["date"] <= pd.Timestamp(bounds[1])]
            stage_rows.to_csv(output_dir / f"observations_{universe_name}_{stage}.csv", index=False, encoding="utf-8-sig")
            for factor in ("amount_ratio_7_20", "volume_ratio_7_20", "amount_7_share", "ma10_slope_5d"):
                summaries.append(summarize_factor(stage_rows, factor, universe_name, stage))
            regime_summaries.append(summarize_regimes(stage_rows, universe_name, stage))
    summary = pd.concat(summaries, ignore_index=True)
    regime_summary = pd.concat(regime_summaries, ignore_index=True)
    summary.to_csv(output_dir / "factor_summary.csv", index=False, encoding="utf-8-sig")
    regime_summary.to_csv(output_dir / "regime_summary.csv", index=False, encoding="utf-8-sig")
    metadata = {"events": "class_2 + class_3", "flow": "7-session mean / prior 20-session mean", "entry": "next session open", "horizons": HORIZONS, "common_universe": "all 15 ETFs available"}
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    report = (
        "# 0AMV 买点 ETF 个股截面研究\n\n"
        "主因子为成交额乖离，成交量为稳健性复核。收益从信号后下一交易日开盘计算。\n\n"
        "## 因子分层\n\n" + _markdown_table(summary.round(3))
        + "\n\n## 趋势与因子交互\n\n" + _markdown_table(regime_summary.round(3)) + "\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf-dir", type=Path, default=ETF_DIR)
    parser.add_argument("--reference", type=Path, default=ETF_DIR / f"{REFERENCE_ETF}.csv")
    parser.add_argument("--output", type=Path, default=Path("data/factor_research_runs/amv_buy_etf_cross_section"))
    args = parser.parse_args()
    print(run_research(args.amv, args.etf_dir, args.reference, args.output).to_string(index=False))


if __name__ == "__main__":
    main()
