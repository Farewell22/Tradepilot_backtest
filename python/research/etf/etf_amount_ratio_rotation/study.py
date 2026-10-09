"""Rotate 0AMV class-2/class-3 entries into low-flow, uptrend ETFs."""
from __future__ import annotations

from python.research.date_scope import scope_frame_dates, scoped_ranges

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from python.factors.amv_buy_points import analyze_amv_buy_points
from python.strategies.etf_amv.strategy import normalize_etf_history, normalize_etf_intraday
from python.research.etf.amv_buy_etf_cross_section.study import (
    add_flow_trend_features,
    aggregate_intraday_etf,
)
from python.research.etf.etf_kdj_rotation.study import (
    CANDIDATES,
    COMMON_START,
    ETF_DIR,
    REFERENCE_ETF,
    REFERENCE_NAME,
    STAGES,
    _load_etfs,
    _next_reference_session,
    run_rotation_backtest,
)
from python.research.amv.ma10_above_ma30_gap.study import (
    INITIAL_CASH,
    _metrics,
    _next_session_schedule,
    generate_buy_signals,
    generate_trend_exit_signals,
)
from python.factor_research.data import load_amv_csv


RUN_DIR = Path("data/backtest_runs/etf_amount_ratio_rotation_0amv")
MIN_RANKED_CANDIDATES = 5


def _quintile(values: pd.Series) -> pd.Series:
    """Assign deterministic Q1--Q5 labels, with Q1 representing the smallest values."""
    ranks = values.rank(method="first")
    return pd.qcut(ranks, 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"]).astype("string")


def choose_low_flow_candidate(candidates: pd.DataFrame) -> pd.Series | None:
    """Select an uptrend ETF from amount Q1--Q3 while rejecting volume Q5."""
    if candidates.empty:
        return None
    required = {"code", "ma10_above_ma30", "amount_ratio_7_20", "volume_ratio_7_20"}
    missing = required.difference(candidates.columns)
    if missing:
        raise ValueError(f"候选数据缺少列: {', '.join(sorted(missing))}")
    ranked = candidates.loc[
        candidates["ma10_above_ma30"].eq(True)
        & candidates["amount_ratio_7_20"].notna()
        & candidates["volume_ratio_7_20"].notna()
    ].copy()
    if len(ranked) < MIN_RANKED_CANDIDATES:
        return None
    ranked["amount_quintile"] = _quintile(ranked["amount_ratio_7_20"])
    ranked["volume_quintile"] = _quintile(ranked["volume_ratio_7_20"])
    eligible = ranked.loc[
        ranked["amount_quintile"].isin(["Q1", "Q2", "Q3"])
        & ranked["volume_quintile"].ne("Q5")
    ]
    if eligible.empty:
        return None
    return eligible.sort_values(["amount_ratio_7_20", "code"], kind="mergesort").iloc[0]


def _load_factor_daily(etf_dir: Path) -> dict[str, pd.DataFrame]:
    output: dict[str, pd.DataFrame] = {}
    for code in CANDIDATES:
        path = etf_dir / f"{code}.csv"
        if not path.exists():
            raise FileNotFoundError(f"ETF 数据不存在: {path}")
        output[code] = add_flow_trend_features(aggregate_intraday_etf(pd.read_csv(path)))
    return output


def _candidate_snapshot(as_of: pd.Timestamp, factor_daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[pd.Series] = []
    for code, daily in factor_daily.items():
        history = daily.loc[daily["date"] <= as_of]
        if history.empty or history.iloc[-1]["date"] != as_of:
            continue
        row = history.iloc[-1].copy()
        row["code"] = code
        row["name"] = CANDIDATES[code]
        rows.append(row)
    return pd.DataFrame(rows)


def build_selection_schedule(
    buy_signals: pd.DataFrame,
    factor_daily: dict[str, pd.DataFrame],
    reference_dates: pd.Series,
    common_only: bool,
) -> tuple[dict[pd.Timestamp, dict], pd.DataFrame]:
    """Choose one eligible ETF at each next-session 0AMV entry, or fall back to 510300."""
    schedule: dict[pd.Timestamp, dict] = {}
    selections: list[dict] = []
    priority = {"class_3": 1, "class_2": 2}
    for signal in buy_signals.itertuples():
        signal_date = pd.Timestamp(signal.date).normalize()
        if common_only and signal_date < COMMON_START:
            continue
        execution_date = _next_reference_session(signal_date, reference_dates)
        if execution_date is None:
            continue
        snapshot = _candidate_snapshot(signal_date, factor_daily)
        selected = choose_low_flow_candidate(snapshot)
        item = {
            "code": selected.code if selected is not None else REFERENCE_ETF,
            "name": selected.name if selected is not None else REFERENCE_NAME,
            "signal_type": signal.signal_type,
            "signal_date": signal_date,
            "selection_type": "low_amount_ratio" if selected is not None else "fallback_510300",
            "amount_ratio_7_20": float(selected.amount_ratio_7_20) if selected is not None else np.nan,
            "volume_ratio_7_20": float(selected.volume_ratio_7_20) if selected is not None else np.nan,
            "amount_quintile": str(selected.amount_quintile) if selected is not None else "fallback",
            "volume_quintile": str(selected.volume_quintile) if selected is not None else "fallback",
            "candidate_count": int(len(snapshot)),
            "trend_candidate_count": int(snapshot.get("ma10_above_ma30", pd.Series(dtype=bool)).eq(True).sum()),
            # Kept for the reusable execution engine's ledger schema; this strategy does not rank on them.
            "rs20": np.nan,
            "gap10": np.nan,
        }
        current = schedule.get(execution_date)
        if current is None or priority[item["signal_type"]] > priority[current["signal_type"]]:
            schedule[execution_date] = item
        selections.append({**item, "execution_date": execution_date})
    return schedule, pd.DataFrame(selections)


def _annual_summary(nav: pd.DataFrame) -> pd.DataFrame:
    frame = nav.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["year"] = frame["date"].dt.year
    rows: list[dict] = []
    prior_nav = INITIAL_CASH
    for year, group in frame.groupby("year", sort=True):
        values = group["nav"].astype(float)
        rows.append({
            "year": int(year),
            "return_pct": (float(values.iloc[-1]) / prior_nav - 1.0) * 100.0,
            "max_drawdown_pct": (values / values.cummax() - 1.0).min() * 100.0,
            "end_nav": float(values.iloc[-1]),
        })
        prior_nav = float(values.iloc[-1])
    return pd.DataFrame(rows)


def attach_selection_metadata(trades: pd.DataFrame, selections: pd.DataFrame) -> pd.DataFrame:
    """Join the entry-day factor choice to execution rows without colliding with engine fields."""
    if trades.empty:
        return trades.copy()
    selection_columns = [
        "execution_date", "selection_type", "amount_ratio_7_20", "volume_ratio_7_20",
        "amount_quintile", "volume_quintile", "candidate_count", "trend_candidate_count",
    ]
    lookup = selections.loc[:, selection_columns].copy()
    lookup["buy_date"] = pd.to_datetime(lookup.pop("execution_date")).dt.strftime("%Y%m%d")
    return trades.drop(columns=["selection_type"], errors="ignore").merge(lookup, on="buy_date", how="left")


def run_research(amv_path: Path, etf_dir: Path, reference_path: Path, output_dir: Path = RUN_DIR) -> pd.DataFrame:
    """Run TRAIN/OOS dynamic and common-universe amount-ratio rotation backtests."""
    amv = load_amv_csv(amv_path)
    raw_reference = pd.read_csv(reference_path)
    reference_daily = normalize_etf_history(raw_reference).sort_values("date").reset_index(drop=True)
    factor_daily = _load_factor_daily(etf_dir)
    candidate_daily, candidate_intraday = _load_etfs(etf_dir)
    candidate_daily[REFERENCE_ETF] = reference_daily
    candidate_intraday[REFERENCE_ETF] = normalize_etf_intraday(raw_reference).sort_values("date").reset_index(drop=True)
    buy_signals = generate_buy_signals(amv).loc[lambda frame: frame["signal_type"].isin(["class_2", "class_3"])]
    trend = generate_trend_exit_signals(amv)
    sell_points, _ = analyze_amv_buy_points(amv)
    trend_schedule = _next_session_schedule(trend, reference_daily["date"], "exit_type")
    low_schedule = _next_session_schedule(sell_points[["date", "sell_momentum_warning_types"]], reference_daily["date"], "sell_momentum_warning_types")
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict] = []
    for universe, common_only in (("dynamic_universe", False), ("common_universe", True)):
        selection_schedule, selections = build_selection_schedule(buy_signals, factor_daily, reference_daily["date"], common_only)
        scope_frame_dates(selections, "execution_date").to_csv(
            output_dir / f"selections_{universe}.csv", index=False, encoding="utf-8-sig"
        )
        for stage, (start, end) in scoped_ranges(STAGES).items():
            stage_start = max(pd.Timestamp(start), COMMON_START) if common_only and stage == "train" else pd.Timestamp(start)
            stage_reference = reference_daily.loc[reference_daily["date"].between(stage_start, end)].reset_index(drop=True)
            allowed = set(stage_reference["date"])
            result = run_rotation_backtest(
                stage_reference, candidate_daily, candidate_intraday,
                {date: item for date, item in selection_schedule.items() if date in allowed},
                {date: kinds for date, kinds in trend_schedule.items() if date in allowed},
                {date: kinds for date, kinds in low_schedule.items() if date in allowed},
            )
            metrics = _metrics(result)
            nav = result.nav.copy()
            nav["return_pct"] = nav["nav"].pct_change().fillna(0.0) * 100.0
            nav["drawdown_pct"] = (nav["nav"] / nav["nav"].cummax() - 1.0) * 100.0
            trades = result.trades.copy()
            if not trades.empty:
                trades = attach_selection_metadata(trades, selections)
            prefix = f"{universe}_{stage}"
            nav.to_csv(output_dir / f"nav_{prefix}.csv", index=False, encoding="utf-8-sig")
            trades.to_csv(output_dir / f"trades_{prefix}.csv", index=False, encoding="utf-8-sig")
            _annual_summary(nav).to_csv(output_dir / f"annual_{prefix}.csv", index=False, encoding="utf-8-sig")
            summaries.append({
                "universe": universe, "stage": stage, "stage_start": stage_start.strftime("%Y-%m-%d"),
                "entry_signal_count": sum(date in allowed for date in selection_schedule),
                "fallback_510300_count": int(sum(item["selection_type"] == "fallback_510300" and date in allowed for date, item in selection_schedule.items())),
                **metrics,
            })
    summary = pd.DataFrame(summaries)
    summary.to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(
        "# 0AMV 成交额低分位 ETF 轮动回测\n\n"
        "动态候选池为主结果。二类/三类0AMV买点后，先保留MA10>MA30的ETF，按成交额乖离从低到高选择Q1-Q3，剔除成交量乖离Q5；无候选则买510300。卖出规则沿用低动量减仓、MA10<=MA30清仓、5%止损与7%后实体低点止盈。\n\n"
        + summary.to_csv(index=False) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf-dir", type=Path, default=ETF_DIR)
    parser.add_argument("--reference", type=Path, default=ETF_DIR / f"{REFERENCE_ETF}.csv")
    parser.add_argument("--output", type=Path, default=RUN_DIR)
    args = parser.parse_args()
    print(run_research(args.amv, args.etf_dir, args.reference, args.output).to_string(index=False))


if __name__ == "__main__":
    main()
