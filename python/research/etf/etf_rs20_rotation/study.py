"""Rotate 0AMV class-2/class-3 entries into the strongest RS20 continuation ETF."""
from __future__ import annotations

from python.research.date_scope import scope_frame_dates, scoped_ranges

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from python.factors.amv_buy_points import analyze_amv_buy_points
from python.strategies.etf_amv.strategy import normalize_etf_history, normalize_etf_intraday
from python.research.etf.etf_kdj_rotation.study import (
    ETF_DIR,
    REFERENCE_ETF,
    REFERENCE_NAME,
    STAGES,
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


RUN_DIR = Path("data/backtest_runs/etf_rs20_rotation_0amv")
CONTINUATION_CANDIDATES = {
    "159928.SZ": "消费",
    "512660.SH": "军工",
    "512720.SH": "计算机",
    "512760.SH": "芯片/半导体",
    "512880.SH": "证券",
    "515030.SH": "新能源车",
    "515050.SH": "通信",
}
SIGNAL_TYPES = ("class_2", "class_3")


def choose_rs20_candidate(candidates: pd.DataFrame) -> pd.Series | None:
    """Choose the largest point-in-time RS20, resolving ties by ETF code."""
    if candidates.empty:
        return None
    required = {"code", "rs20"}
    missing = required.difference(candidates.columns)
    if missing:
        raise ValueError(f"候选数据缺少列: {', '.join(sorted(missing))}")
    eligible = candidates.loc[candidates["rs20"].notna()].copy()
    if eligible.empty:
        return None
    return eligible.sort_values(["rs20", "code"], ascending=[False, True], kind="mergesort").iloc[0]


def candidate_rs20(
    as_of: pd.Timestamp,
    candidate_daily: dict[str, pd.DataFrame],
    reference_daily: pd.DataFrame,
) -> pd.DataFrame:
    """Return candidates with 20-session RS20 using only matched closes through ``as_of``."""
    as_of = pd.Timestamp(as_of).normalize()
    reference = reference_daily.loc[:, ["date", "close"]].copy()
    reference["date"] = pd.to_datetime(reference["date"], errors="raise").dt.normalize()
    reference = reference.loc[reference["date"] <= as_of].rename(columns={"close": "reference_close"})
    rows: list[dict] = []
    for code, daily in candidate_daily.items():
        asset = daily.loc[:, ["date", "close"]].copy()
        asset["date"] = pd.to_datetime(asset["date"], errors="raise").dt.normalize()
        asset = asset.loc[asset["date"] <= as_of].rename(columns={"close": "asset_close"})
        matched = asset.merge(reference, on="date", how="inner").sort_values("date").reset_index(drop=True)
        if len(matched) < 21 or matched.iloc[-1]["date"] != as_of:
            continue
        current = matched.iloc[-1]
        prior = matched.iloc[-21]
        asset_return = float(current.asset_close / prior.asset_close - 1.0)
        reference_return = float(current.reference_close / prior.reference_close - 1.0)
        rows.append({
            "code": code,
            "name": CONTINUATION_CANDIDATES.get(code, code),
            "rs20": asset_return - reference_return,
            "asset_return_20": asset_return,
            "reference_return_20": reference_return,
        })
    return pd.DataFrame(rows)


def build_selection_schedule(
    buy_signals: pd.DataFrame,
    candidate_daily: dict[str, pd.DataFrame],
    reference_daily: pd.DataFrame,
    reference_dates: pd.Series,
) -> tuple[dict[pd.Timestamp, dict], pd.DataFrame]:
    """Select RS20 Top-1 at each next-session entry, with a 510300 fallback."""
    schedule: dict[pd.Timestamp, dict] = {}
    selections: list[dict] = []
    sessions = pd.to_datetime(reference_dates, errors="raise")
    first_reference_session = pd.Timestamp(sessions.min()).normalize() if len(sessions) else None
    for signal in buy_signals.itertuples():
        signal_date = pd.Timestamp(signal.date).normalize()
        if first_reference_session is None or signal_date < first_reference_session:
            continue
        execution_date = _next_reference_session(signal_date, reference_dates)
        if execution_date is None:
            continue
        ranking = candidate_rs20(signal_date, candidate_daily, reference_daily)
        selected = choose_rs20_candidate(ranking)
        item = {
            "code": selected["code"] if selected is not None else REFERENCE_ETF,
            "name": selected["name"] if selected is not None else REFERENCE_NAME,
            "signal_type": signal.signal_type,
            "signal_date": signal_date,
            "selection_type": "rs20_top1" if selected is not None else "fallback_510300",
            "rs20": float(selected["rs20"]) if selected is not None else np.nan,
            "gap10": np.nan,
            "candidate_count": int(len(ranking)),
            "is_fallback": selected is None,
        }
        schedule[execution_date] = item
        selections.append({**item, "execution_date": execution_date})
    columns = [
        "code", "name", "signal_type", "signal_date", "execution_date", "selection_type",
        "rs20", "gap10", "candidate_count", "is_fallback",
    ]
    return schedule, pd.DataFrame(selections, columns=columns)


def _load_candidate_etfs(etf_dir: Path) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    daily: dict[str, pd.DataFrame] = {}
    intraday: dict[str, pd.DataFrame] = {}
    for code in CONTINUATION_CANDIDATES:
        path = etf_dir / f"{code}.csv"
        if not path.exists():
            raise FileNotFoundError(f"ETF 数据不存在: {path}")
        raw = pd.read_csv(path)
        daily[code] = normalize_etf_history(raw).sort_values("date").reset_index(drop=True)
        intraday[code] = normalize_etf_intraday(raw).sort_values("date").reset_index(drop=True)
    return daily, intraday


def _annual_summary(nav: pd.DataFrame) -> pd.DataFrame:
    frame = nav.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["year"] = frame["date"].dt.year
    prior_nav = INITIAL_CASH
    rows: list[dict] = []
    for year, values in frame.groupby("year", sort=True):
        nav_values = values["nav"].astype(float)
        rows.append({
            "year": int(year),
            "return_pct": (float(nav_values.iloc[-1]) / prior_nav - 1.0) * 100.0,
            "max_drawdown_pct": (nav_values / nav_values.cummax() - 1.0).min() * 100.0,
            "end_nav": float(nav_values.iloc[-1]),
        })
        prior_nav = float(nav_values.iloc[-1])
    return pd.DataFrame(rows)


def attach_selection_metadata(trades: pd.DataFrame, selections: pd.DataFrame) -> pd.DataFrame:
    """Attach selection-only metadata that the shared execution engine does not retain."""
    if trades.empty:
        return trades.copy()
    lookup = selections.loc[:, ["execution_date", "candidate_count", "is_fallback"]].copy()
    lookup["buy_date"] = pd.to_datetime(lookup.pop("execution_date")).dt.strftime("%Y%m%d")
    return trades.merge(lookup, on="buy_date", how="left")


def run_research(
    amv_path: Path,
    etf_dir: Path,
    reference_path: Path,
    output_dir: Path = RUN_DIR,
) -> pd.DataFrame:
    """Run independent class-2/class-3 TRAIN and OOS RS20 Top-1 backtests."""
    amv = load_amv_csv(amv_path)
    raw_reference = pd.read_csv(reference_path)
    reference_daily = normalize_etf_history(raw_reference).sort_values("date").reset_index(drop=True)
    candidate_daily, candidate_intraday = _load_candidate_etfs(etf_dir)
    candidate_daily[REFERENCE_ETF] = reference_daily
    candidate_intraday[REFERENCE_ETF] = normalize_etf_intraday(raw_reference).sort_values("date").reset_index(drop=True)
    buy_signals = generate_buy_signals(amv).loc[lambda frame: frame["signal_type"].isin(SIGNAL_TYPES)]
    trend = generate_trend_exit_signals(amv)
    sell_points, _ = analyze_amv_buy_points(amv)
    trend_schedule = _next_session_schedule(trend, reference_daily["date"], "exit_type")
    momentum_schedule = _next_session_schedule(
        sell_points[["date", "sell_momentum_warning_types"]],
        reference_daily["date"],
        "sell_momentum_warning_types",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict] = []
    for signal_type in SIGNAL_TYPES:
        class_signals = buy_signals.loc[buy_signals["signal_type"] == signal_type]
        schedule, selections = build_selection_schedule(
            class_signals, {code: candidate_daily[code] for code in CONTINUATION_CANDIDATES},
            reference_daily, reference_daily["date"],
        )
        scope_frame_dates(selections, "execution_date").to_csv(
            output_dir / f"selections_{signal_type}.csv", index=False, encoding="utf-8-sig"
        )
        for stage, (start, end) in scoped_ranges(STAGES).items():
            stage_reference = reference_daily.loc[reference_daily["date"].between(start, end)].reset_index(drop=True)
            allowed_dates = set(stage_reference["date"])
            result = run_rotation_backtest(
                stage_reference,
                candidate_daily,
                candidate_intraday,
                {date: item for date, item in schedule.items() if date in allowed_dates},
                {date: values for date, values in trend_schedule.items() if date in allowed_dates},
                {date: values for date, values in momentum_schedule.items() if date in allowed_dates},
                stop_loss_pct=0.03,
                profit_trail_pct=0.05,
            )
            nav = result.nav.copy()
            nav["return_pct"] = nav["nav"].pct_change().fillna(0.0) * 100.0
            nav["drawdown_pct"] = (nav["nav"] / nav["nav"].cummax() - 1.0) * 100.0
            trades = attach_selection_metadata(result.trades, selections)
            suffix = f"{signal_type}_{stage}"
            nav.to_csv(output_dir / f"nav_{suffix}.csv", index=False, encoding="utf-8-sig")
            _annual_summary(nav).to_csv(output_dir / f"annual_{suffix}.csv", index=False, encoding="utf-8-sig")
            trades.to_csv(output_dir / f"trades_{suffix}.csv", index=False, encoding="utf-8-sig")
            summaries.append({
                "signal_type": signal_type,
                "stage": stage,
                "stage_start": str(start),
                "stage_end": str(end),
                "entry_signal_count": int(sum(date in allowed_dates for date in schedule)),
                "fallback_510300_count": int(sum(
                    item["is_fallback"] and date in allowed_dates for date, item in schedule.items()
                )),
                "ignored_buy_signal_count": result.ignored_buy_signals,
                "oos_exit_row_count": int(len(trades)) if stage == "oos" else np.nan,
                **_metrics(result),
            })
    summary = pd.DataFrame(summaries)
    summary.to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    report = (
        "# 0AMV RS20 ETF 选股因子策略回测\n\n"
        "二类、三类买点分别回测。每个信号日收盘，用与510300匹配的20个此前交易日计算RS20，"
        "从动态可用的延续行业池中选择Top-1；无可用候选时回退510300。持仓中的重叠买点会被忽略，"
        "卖出规则沿用MA10<=MA30趋势退出、低动量减仓、5%止损及7%后实体低点止盈。\n\n"
        + summary.to_csv(index=False) + "\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
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
