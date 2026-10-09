"""Point-in-time cross-sectional relative-volume research for industry ETFs."""
from __future__ import annotations

from python.research.date_scope import scoped_ranges

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from python.research.etf.amv_buy_etf_cross_section.study import aggregate_intraday_etf, attach_forward_returns
from python.research.etf.etf_kdj_rotation.study import CANDIDATES, ETF_DIR, REFERENCE_ETF
from python.research.amv.ma10_above_ma30_gap.study import generate_buy_signals
from python.factor_research.data import load_amv_csv


HORIZONS = (5, 10, 20, 60)
FACTORS = ("volume_ratio_7_20", "volume_ratio_30_80")
MIN_CROSS_SECTION = 5
SAMPLES = {"train": ("2015-01-01", "2023-12-31"), "oos": ("2024-01-01", "2025-12-31")}


def add_relative_volume_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Compute only-close-known volume ratios and the MA20 rising trend state."""
    result = daily.copy().sort_values("date").reset_index(drop=True)
    result["date"] = pd.to_datetime(result["date"], errors="raise").dt.normalize()
    for column in ("close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="raise")

    volume = result["volume"]
    result["volume_ratio_7_20"] = (
        volume.rolling(7, min_periods=7).mean()
        / volume.shift(7).rolling(20, min_periods=20).mean()
    )
    result["volume_ratio_30_80"] = (
        volume.rolling(30, min_periods=30).mean()
        / volume.shift(30).rolling(80, min_periods=80).mean()
    )
    result["ma20"] = result["close"].rolling(20, min_periods=20).mean()
    result["trend_up"] = (result["close"] > result["ma20"]) & (result["ma20"] > result["ma20"].shift(5))
    return result


def _quintiles(values: pd.Series) -> pd.Series:
    """Return stable Q1--Q5 labels, or missing values when a day cannot be split."""
    output = pd.Series(pd.NA, index=values.index, dtype="string")
    valid = values.dropna()
    if len(valid) < MIN_CROSS_SECTION or valid.nunique() < MIN_CROSS_SECTION:
        return output
    ranks = valid.rank(method="first")
    output.loc[valid.index] = pd.qcut(ranks, 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"]).astype("string")
    return output


def assign_cross_section_quintiles(observations: pd.DataFrame) -> pd.DataFrame:
    """Assign per-date factor quintiles among ETFs that pass the MA20 trend filter."""
    result = observations.copy()
    for factor in FACTORS:
        result[f"{factor}_quintile"] = pd.Series(pd.NA, index=result.index, dtype="string")
    eligible = result.loc[result["trend_up"].eq(True)]
    group_columns = ["date"] + (["sample_type"] if "sample_type" in result.columns else [])
    for _, rows in eligible.groupby(group_columns, sort=False):
        for factor in FACTORS:
            ordered = rows.sort_values([factor, "code"], kind="mergesort")
            result.loc[ordered.index, f"{factor}_quintile"] = _quintiles(ordered[factor])
    return result


def build_observations(
    events: pd.DataFrame,
    universe: dict[str, pd.DataFrame],
    reference: pd.DataFrame,
) -> pd.DataFrame:
    """Attach point-in-time factors and tradable labels to every event/ETF pair."""
    event_rows = events.copy()
    event_rows["date"] = pd.to_datetime(event_rows["date"], errors="raise").dt.normalize()
    if "sample_type" not in event_rows:
        event_rows["sample_type"] = "full"
    reference_labels = attach_forward_returns(event_rows[["date"]].drop_duplicates(), reference, HORIZONS).set_index("date")
    rows: list[pd.DataFrame] = []
    for code, daily in universe.items():
        featured = add_relative_volume_features(daily)
        merged = event_rows.merge(featured, on="date", how="left")
        merged = merged.loc[merged["close"].notna()].copy()
        if merged.empty:
            continue
        labels = attach_forward_returns(merged[["date"]].drop_duplicates(), featured, HORIZONS)
        label_columns = ["date", "entry_date", "entry_open"] + [f"forward_return_{horizon}_pct" for horizon in HORIZONS]
        merged = merged.merge(labels[label_columns], on="date", how="left")
        merged["code"] = code
        for horizon in HORIZONS:
            reference_column = f"reference_forward_return_{horizon}_pct"
            target_column = f"forward_return_{horizon}_pct"
            merged[reference_column] = merged["date"].map(reference_labels[target_column])
            merged[f"excess_return_{horizon}_pct"] = merged[target_column] - merged[reference_column]
        rows.append(merged)
    if not rows:
        return pd.DataFrame()
    return assign_cross_section_quintiles(pd.concat(rows, ignore_index=True))


def summarize_factor(
    observations: pd.DataFrame,
    factor: str,
    universe_name: str,
    stage: str,
    horizons: tuple[int, ...] = HORIZONS,
) -> pd.DataFrame:
    """Summarize event-equal-weighted quintiles, spread, and daily IC for one factor."""
    rows: list[dict[str, object]] = []
    quintile_column = f"{factor}_quintile"
    for sample_type, sample_rows in observations.groupby("sample_type", sort=True):
        for horizon in horizons:
            target = f"forward_return_{horizon}_pct"
            excess = f"excess_return_{horizon}_pct"
            event_groups = sample_rows.dropna(subset=[quintile_column, target]).groupby(
                ["date", quintile_column], observed=True
            )[[target, excess]].mean()
            group_means: dict[str, pd.DataFrame] = {}
            for quintile in ("Q1", "Q2", "Q3", "Q4", "Q5"):
                values = event_groups.xs(quintile, level=1, drop_level=False) if quintile in event_groups.index.get_level_values(1) else pd.DataFrame()
                group_means[quintile] = values
                rows.append({
                    "sample_type": sample_type, "universe": universe_name, "stage": stage,
                    "factor": factor, "horizon": horizon, "quintile": quintile,
                    "event_count": len(values), "mean_return_pct": values[target].mean() if not values.empty else np.nan,
                    "mean_excess_return_pct": values[excess].mean() if not values.empty else np.nan,
                    "win_rate_pct": (values[target] > 0).mean() * 100 if not values.empty else np.nan,
                })
            q1 = group_means["Q1"].droplevel(1) if not group_means["Q1"].empty else group_means["Q1"]
            q5 = group_means["Q5"].droplevel(1) if not group_means["Q5"].empty else group_means["Q5"]
            paired = q5[[target, excess]].rename(columns={target: "q5_return", excess: "q5_excess"}).join(
                q1[[target, excess]].rename(columns={target: "q1_return", excess: "q1_excess"}), how="inner"
            )
            rows.append({
                "sample_type": sample_type, "universe": universe_name, "stage": stage,
                "factor": factor, "horizon": horizon, "quintile": "Q5-Q1", "event_count": len(paired),
                "mean_return_pct": (paired["q5_return"] - paired["q1_return"]).mean(),
                "mean_excess_return_pct": (paired["q5_excess"] - paired["q1_excess"]).mean(),
                "win_rate_pct": np.nan,
            })
            eligible_rows = sample_rows.dropna(subset=[quintile_column, target])
            ics = eligible_rows.groupby("date", sort=False).apply(
                lambda frame: frame[[factor, target]].dropna().corr(method="spearman").iloc[0, 1]
                if len(frame[[factor, target]].dropna()) >= MIN_CROSS_SECTION else np.nan,
                include_groups=False,
            ).dropna()
            top = eligible_rows.sort_values(["date", factor, "code"], ascending=[True, False, True]).groupby("date", as_index=False).first()
            rows.append({
                "sample_type": sample_type, "universe": universe_name, "stage": stage,
                "factor": factor, "horizon": horizon, "quintile": "IC/top1", "event_count": len(ics),
                "mean_return_pct": top[target].mean(), "mean_excess_return_pct": top[excess].mean(),
                "win_rate_pct": (top[target] > 0).mean() * 100, "mean_spearman_ic": ics.mean(),
                "positive_ic_rate_pct": (ics > 0).mean() * 100,
            })
    return pd.DataFrame(rows)


def _load_universe(etf_dir: Path) -> dict[str, pd.DataFrame]:
    universe: dict[str, pd.DataFrame] = {}
    for code in CANDIDATES:
        path = etf_dir / f"{code}.csv"
        if not path.exists():
            raise FileNotFoundError(f"ETF 数据不存在: {path}")
        universe[code] = aggregate_intraday_etf(pd.read_csv(path))
    return universe


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    rows = frame.fillna("").astype(str).itertuples(index=False, name=None)
    return "\n".join([header, divider, *("| " + " | ".join(row) + " |" for row in rows)])


def _sample_events(reference: pd.DataFrame, buy_signals: pd.DataFrame) -> pd.DataFrame:
    full = pd.DataFrame({"date": reference["date"].drop_duplicates(), "sample_type": "full"})
    buy = buy_signals.loc[buy_signals["signal_type"].isin(["class_2", "class_3"]), ["date"]].copy()
    buy["sample_type"] = "buy_point"
    return pd.concat([full, buy], ignore_index=True).drop_duplicates(["date", "sample_type"])


def _stage_rows(observations: pd.DataFrame, bounds: tuple[str | None, str | None]) -> pd.DataFrame:
    start, end = bounds
    rows = observations
    if start is not None:
        rows = rows.loc[rows["date"] >= pd.Timestamp(start)]
    if end is not None:
        rows = rows.loc[rows["date"] <= pd.Timestamp(end)]
    return rows.copy()


def run_research(amv_path: Path, etf_dir: Path, reference_path: Path, output_dir: Path) -> pd.DataFrame:
    """Run the full-day and 0AMV-buy-point relative-volume study."""
    amv = load_amv_csv(amv_path)
    reference = aggregate_intraday_etf(pd.read_csv(reference_path))
    events = _sample_events(reference, generate_buy_signals(amv))
    universe = _load_universe(etf_dir)
    all_observations = build_observations(events, universe, reference)
    output_dir.mkdir(parents=True, exist_ok=True)
    common_start = max(frame["date"].min() for frame in universe.values())
    summaries: list[pd.DataFrame] = []
    for universe_name, rows in (
        ("dynamic", all_observations),
        ("common", all_observations.loc[all_observations["date"] >= common_start].copy()),
    ):
        for stage, bounds in scoped_ranges(SAMPLES, include_all=True).items():
            stage_rows = _stage_rows(rows, bounds)
            stage_rows.to_csv(output_dir / f"observations_{universe_name}_{stage}.csv", index=False, encoding="utf-8-sig")
            for factor in FACTORS:
                summaries.append(summarize_factor(stage_rows, factor, universe_name, stage))
    summary = pd.concat(summaries, ignore_index=True)
    summary.to_csv(output_dir / "factor_summary.csv", index=False, encoding="utf-8-sig")
    metadata = {
        "samples": {"full": "every reference-ETF trading day", "buy_point": "0AMV class_2 + class_3"},
        "factors": {
            "volume_ratio_7_20": "7-session mean volume / prior 20-session mean volume",
            "volume_ratio_30_80": "30-session mean volume / prior 80-session mean volume",
        },
        "trend": "close > MA20 and MA20(t) > MA20(t-5)",
        "entry": "next ETF session open", "horizons": HORIZONS, "benchmark": REFERENCE_ETF,
        "universe": "dynamic primary plus common-start robustness sample",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    report = (
        "# ETF 相对成交量因子研究\n\n"
        "仅在收盘站上上升 MA20 的 ETF 中，按相对自身历史的成交量放大程度做日度横截面五分位。"
        "收益从信号后下一交易日开盘开始计算；本研究不是交易回测。\n\n"
        "## 因子汇总\n\n" + _markdown_table(summary.round(3)) + "\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf-dir", type=Path, default=ETF_DIR)
    parser.add_argument("--reference", type=Path, default=ETF_DIR / f"{REFERENCE_ETF}.csv")
    parser.add_argument("--output", type=Path, default=Path("data/factor_research_runs/etf_relative_volume"))
    args = parser.parse_args()
    print(run_research(args.amv, args.etf_dir, args.reference, args.output).to_string(index=False))


if __name__ == "__main__":
    main()
