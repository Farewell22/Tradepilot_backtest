"""0AMV 二/三类买点触发后，以行业相对强度替换默认的沪深300 ETF。"""
from __future__ import annotations

from python.research.date_scope import scoped_ranges

import argparse
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from python.factors.amv_buy_points import analyze_amv_buy_points
from python.strategies.etf_amv.strategy import normalize_etf_history, normalize_etf_intraday
from python.research.amv.ma10_above_ma30_gap.study import (
    INITIAL_CASH,
    _metrics,
    _next_session_schedule,
    generate_buy_signals,
    generate_trend_exit_signals,
)
from python.backtest.simulator import calc_buy_cost, calc_sell_proceeds
from python.backtest.broker import FeeConfig
from python.factor_research.data import load_amv_csv
from python.scoring.brick_indicator import compute_kdj


ETF_DIR = Path("data/backtest_data/ETF_60min_2005_2025")
REFERENCE_ETF = "510300.SH"
REFERENCE_NAME = "沪深300ETF"
CANDIDATES = {
    "510880.SH": "红利低波",
    "512800.SH": "银行",
    "512880.SH": "证券",
    "512200.SH": "地产",
    "159928.SZ": "消费",
    "512010.SH": "医药",
    "512400.SH": "有色金属",
    "515220.SH": "煤炭",
    "515210.SH": "钢铁",
    "512660.SH": "军工",
    "512760.SH": "芯片/半导体",
    "512720.SH": "计算机",
    "515050.SH": "通信",
    "512980.SH": "传媒",
    "515030.SH": "新能源车",
}
STAGES = {"train": ("2015-01-01", "2023-12-31"), "oos": ("2024-01-01", "2025-12-31")}
COMMON_START = pd.Timestamp("2020-03-05")


TURNING_MODES = ("daily_only", "weekly_only", "weekly_then_daily", "daily_weekly_both")


def is_low_turning_up(previous_j: float, current_j: float) -> bool:
    """A J value must rebound from <13 while remaining no higher than 20."""
    return bool(previous_j < 13.0 and previous_j < current_j <= 20.0)


def choose_turning_candidate(candidates: pd.DataFrame, mode: str) -> pd.Series | None:
    """Select a single ETF that meets a requested daily/weekly low-turn filter."""
    if mode not in TURNING_MODES:
        raise ValueError(f"unsupported turning mode: {mode}")
    if candidates.empty:
        return None
    if mode == "daily_only":
        eligible, sort_columns = candidates.loc[candidates["daily_turn"]], ["daily_j", "code"]
    elif mode == "weekly_only":
        eligible, sort_columns = candidates.loc[candidates["weekly_turn"]], ["weekly_j", "code"]
    elif mode == "daily_weekly_both":
        eligible, sort_columns = candidates.loc[candidates["daily_turn"] & candidates["weekly_turn"]], ["weekly_j", "daily_j", "code"]
    else:
        weekly = candidates.loc[candidates["weekly_turn"]]
        eligible = weekly if not weekly.empty else candidates.loc[candidates["daily_turn"]]
        sort_columns = ["weekly_j", "daily_j", "code"] if not weekly.empty else ["daily_j", "code"]
    if eligible.empty:
        return None
    return eligible.sort_values(sort_columns, ascending=True, kind="mergesort").iloc[0]


def choose_candidate(candidates: pd.DataFrame) -> pd.Series:
    """Legacy wrapper retained for callers that need the deterministic J-value ordering."""
    if candidates.empty:
        raise ValueError("候选 ETF 为空")
    return candidates.sort_values(
        ["score", "weekly_j", "daily_j", "code"],
        ascending=[False, True, True, True],
        kind="mergesort",
    ).iloc[0]


def choose_highest_ma30_gap(candidates: pd.DataFrame) -> pd.Series:
    """Choose the ETF whose close has the largest positive deviation from its own MA30."""
    if candidates.empty:
        raise ValueError("候选 ETF 为空")
    return candidates.sort_values(["ma30_gap", "code"], ascending=[False, True], kind="mergesort").iloc[0]


def choose_ma10_rising_near_ma10(candidates: pd.DataFrame) -> pd.Series | None:
    """Choose the MA10-rising ETF with the smallest absolute close/MA10 deviation."""
    if candidates.empty:
        return None
    eligible = candidates.loc[candidates["ma10_rising"]].copy()
    if eligible.empty:
        return None
    eligible["abs_gap10"] = eligible["gap10"].abs()
    return eligible.sort_values(["abs_gap10", "code"], ascending=[True, True], kind="mergesort").iloc[0]


def choose_relative_strength_candidate(candidates: pd.DataFrame) -> pd.Series | None:
    """Select the strongest industry only after trend, relative-strength, and heat filters pass."""
    if candidates.empty:
        return None
    eligible = candidates.loc[
        candidates["ma10_above_ma30"] & (candidates["rs20"] > 0.0) & candidates["gap10_below_p80"]
    ]
    if eligible.empty:
        return None
    return eligible.sort_values(["rs20", "code"], ascending=[False, True], kind="mergesort").iloc[0]


def candidate_relative_strength(
    as_of: pd.Timestamp,
    candidate_daily: dict[str, pd.DataFrame],
    reference_daily: pd.DataFrame,
) -> pd.DataFrame:
    """Compute point-in-time industry RS20 versus 510300 and a prior-history gap10 heat cap."""
    reference = reference_daily.loc[reference_daily["date"] <= as_of, ["date", "close"]].copy()
    if len(reference) < 21 or reference.iloc[-1]["date"] != as_of:
        return pd.DataFrame()
    reference_return = float(reference.iloc[-1]["close"] / reference.iloc[-21]["close"] - 1.0)
    rows: list[dict] = []
    for code, daily in candidate_daily.items():
        history = daily.loc[daily["date"] <= as_of, ["date", "close"]].copy()
        if len(history) < 30 or history.iloc[-1]["date"] != as_of:
            continue
        close = history["close"].astype(float)
        ma10 = close.rolling(10, min_periods=10).mean()
        ma30 = close.rolling(30, min_periods=30).mean()
        gap10 = close / ma10 - 1.0
        previous_gaps = gap10.iloc[-251:-1].dropna()
        p80 = previous_gaps.quantile(0.80) if len(previous_gaps) >= 60 else np.nan
        asset_return = float(close.iloc[-1] / close.iloc[-21] - 1.0)
        rows.append({
            "code": code,
            "name": CANDIDATES[code],
            "rs20": asset_return - reference_return,
            "gap10": float(gap10.iloc[-1]),
            "gap10_p80": float(p80) if pd.notna(p80) else np.nan,
            "gap10_below_p80": bool(pd.notna(p80) and gap10.iloc[-1] <= p80),
            "ma10_above_ma30": bool(ma10.iloc[-1] > ma30.iloc[-1]),
        })
    return pd.DataFrame(rows)


def candidate_ma10_states(as_of: pd.Timestamp, candidate_daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return point-in-time MA10 direction and close-to-MA10 deviation for tradable ETFs."""
    rows: list[dict] = []
    for code, daily in candidate_daily.items():
        history = daily.loc[daily["date"] <= as_of, ["date", "close"]].copy()
        if history.empty or history.iloc[-1]["date"] != as_of:
            continue
        ma10 = history["close"].rolling(10, min_periods=10).mean()
        if len(ma10) < 2 or pd.isna(ma10.iloc[-1]) or pd.isna(ma10.iloc[-2]) or ma10.iloc[-1] <= 0:
            continue
        close = float(history.iloc[-1]["close"])
        rows.append({
            "code": code, "name": CANDIDATES[code], "close": close,
            "ma10": float(ma10.iloc[-1]), "gap10": close / float(ma10.iloc[-1]) - 1.0,
            "ma10_rising": bool(ma10.iloc[-1] > ma10.iloc[-2]),
        })
    return pd.DataFrame(rows)


def candidate_ma30_gaps(as_of: pd.Timestamp, candidate_daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return point-in-time close/MA30 deviations for the ETFs tradable on the signal date."""
    rows: list[dict] = []
    for code, daily in candidate_daily.items():
        history = daily.loc[daily["date"] <= as_of, ["date", "close"]].copy()
        if history.empty or history.iloc[-1]["date"] != as_of:
            continue
        ma30 = history["close"].rolling(30, min_periods=30).mean().iloc[-1]
        if pd.isna(ma30) or ma30 <= 0:
            continue
        close = float(history.iloc[-1]["close"])
        rows.append({"code": code, "name": CANDIDATES[code], "close": close, "ma30": float(ma30), "ma30_gap": close / float(ma30) - 1.0})
    return pd.DataFrame(rows)


def _completed_period_bars(daily: pd.DataFrame, as_of: pd.Timestamp, frequency: str) -> pd.DataFrame:
    """Return only fully completed prior weekly/monthly bars as of a daily close."""
    frame = daily.loc[daily["date"] <= as_of, ["date", "high", "low", "close"]].copy()
    if frame.empty:
        return frame
    frame = frame.set_index("date").sort_index()
    if frequency == "W-FRI":
        current = as_of.to_period("W-FRI")
        frame = frame.loc[frame.index.to_period("W-FRI") < current]
    elif frequency == "ME":
        current = as_of.to_period("M")
        frame = frame.loc[frame.index.to_period("M") < current]
    else:
        raise ValueError(f"unsupported frequency: {frequency}")
    if frame.empty:
        return pd.DataFrame(columns=["high", "low", "close"])
    return frame.resample(frequency).agg({"high": "max", "low": "min", "close": "last"}).dropna()


def _last_j(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 50.0
    value = float(compute_kdj(frame)["J"].iloc[-1])
    return value if np.isfinite(value) else 50.0


def candidate_turns(as_of: pd.Timestamp, candidate_daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Point-in-time daily/weekly J and their prior readings for every available ETF."""
    rows: list[dict] = []
    for code, daily in candidate_daily.items():
        history = daily.loc[daily["date"] <= as_of, ["date", "high", "low", "close"]].copy()
        if history.empty or history.iloc[-1]["date"] != as_of:
            continue
        daily_kdj = compute_kdj(history.set_index("date"))
        weekly_kdj = compute_kdj(_completed_period_bars(daily, as_of, "W-FRI"))
        daily_j = float(daily_kdj["J"].iloc[-1])
        daily_prev_j = float(daily_kdj["J"].iloc[-2]) if len(daily_kdj) >= 2 else 50.0
        weekly_j = float(weekly_kdj["J"].iloc[-1]) if not weekly_kdj.empty else 50.0
        weekly_prev_j = float(weekly_kdj["J"].iloc[-2]) if len(weekly_kdj) >= 2 else 50.0
        rows.append({
            "code": code,
            "name": CANDIDATES[code],
            "daily_j": daily_j,
            "daily_prev_j": daily_prev_j,
            "weekly_j": weekly_j,
            "weekly_prev_j": weekly_prev_j,
            "daily_turn": is_low_turning_up(daily_prev_j, daily_j),
            "weekly_turn": is_low_turning_up(weekly_prev_j, weekly_j),
        })
    return pd.DataFrame(rows)


def _load_etfs(etf_dir: Path) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    daily: dict[str, pd.DataFrame] = {}
    intraday: dict[str, pd.DataFrame] = {}
    for code in CANDIDATES:
        path = etf_dir / f"{code}.csv"
        if not path.exists():
            raise FileNotFoundError(f"ETF 数据不存在: {path}")
        raw = pd.read_csv(path)
        daily[code] = normalize_etf_history(raw).sort_values("date").reset_index(drop=True)
        intraday[code] = normalize_etf_intraday(raw).sort_values("date").reset_index(drop=True)
    return daily, intraday


def _next_reference_session(signal_date: pd.Timestamp, reference_dates: pd.Series) -> pd.Timestamp | None:
    values = pd.to_datetime(reference_dates).dt.normalize().drop_duplicates().sort_values().to_numpy(dtype="datetime64[ns]")
    index = values.searchsorted(signal_date.to_datetime64(), side="right")
    return pd.Timestamp(values[index]) if index < len(values) else None


def build_selection_schedule(
    buy_signals: pd.DataFrame,
    candidate_daily: dict[str, pd.DataFrame],
    reference_daily: pd.DataFrame,
    reference_dates: pd.Series,
    common_only: bool,
) -> tuple[dict[pd.Timestamp, dict], pd.DataFrame]:
    """Use a qualified strongest industry, or fall back to 510300, at every 0AMV entry."""
    schedule: dict[pd.Timestamp, dict] = {}
    selections: list[dict] = []
    for signal in buy_signals.itertuples():
        date = pd.Timestamp(signal.date).normalize()
        if common_only and date < COMMON_START:
            continue
        ranking = candidate_relative_strength(date, candidate_daily, reference_daily)
        chosen = choose_relative_strength_candidate(ranking)
        execution_date = _next_reference_session(date, reference_dates)
        if execution_date is None:
            continue
        item = {
            "code": chosen.code if chosen is not None else REFERENCE_ETF,
            "name": chosen.name if chosen is not None else REFERENCE_NAME,
            "signal_type": signal.signal_type,
            "signal_date": date,
            "selection_type": "industry_relative_strength" if chosen is not None else "fallback_510300",
            "rs20": float(chosen.rs20) if chosen is not None else np.nan,
            "gap10": float(chosen.gap10) if chosen is not None else np.nan,
        }
        current = schedule.get(execution_date)
        priority = {"class_3": 1, "class_2": 2}
        if current is None or priority[item["signal_type"]] > priority[current["signal_type"]]:
            schedule[execution_date] = item
        selections.append({**item, "execution_date": execution_date, "candidate_count": len(ranking)})
    return schedule, pd.DataFrame(selections)


@dataclass
class RotationResult:
    final_value: float
    nav: pd.DataFrame
    trades: pd.DataFrame
    ignored_buy_signals: int


def _row_by_date(daily: pd.DataFrame) -> dict[pd.Timestamp, pd.Series]:
    return {pd.Timestamp(row.date).normalize(): row for row in daily.itertuples()}


def _bars_by_date(intraday: pd.DataFrame) -> dict[pd.Timestamp, pd.DataFrame]:
    frame = intraday.copy()
    frame["session"] = pd.to_datetime(frame["date"]).dt.normalize()
    return {pd.Timestamp(day): rows.reset_index(drop=True) for day, rows in frame.groupby("session", sort=False)}


def run_rotation_backtest(
    reference_daily: pd.DataFrame,
    candidate_daily: dict[str, pd.DataFrame],
    candidate_intraday: dict[str, pd.DataFrame],
    buy_schedule: dict[pd.Timestamp, dict],
    trend_exit_schedule: dict[pd.Timestamp, list[str]],
    low_momentum_schedule: dict[pd.Timestamp, list[str]],
    stop_loss_pct: float = 0.05,
    profit_trail_pct: float = 0.07,
    fees: FeeConfig | None = None,
) -> RotationResult:
    """Single-position portfolio: selection only changes the entry ETF; 0AMV exits stay unchanged."""
    prices = reference_daily.loc[:, ["date"]].copy().sort_values("date").reset_index(drop=True)
    daily_maps = {code: _row_by_date(frame) for code, frame in candidate_daily.items()}
    bars_maps = {code: _bars_by_date(frame) for code, frame in candidate_intraday.items()}
    cash, quantity, entry, ignored, sequence = INITIAL_CASH, 0, None, 0, 0
    trades: list[dict] = []
    nav_rows: list[dict] = []
    last_close: dict[str, float] = {}

    def close_position(date: pd.Timestamp, price: float, reason: str, day_index: int, sell_quantity: int) -> None:
        nonlocal cash, quantity, entry
        exec_price, proceeds = calc_sell_proceeds(price, sell_quantity, fees)
        allocated_cost = entry["buy_cost"] * sell_quantity / entry["buy_quantity"]
        remaining = quantity - sell_quantity
        trades.append({
            **entry,
            "buy_cost": allocated_cost,
            "sell_date": date.strftime("%Y%m%d"),
            "sell_signal_price": price,
            "sell_exec_price": exec_price,
            "sell_proceeds": proceeds,
            "sell_reason": reason,
            "sell_quantity": sell_quantity,
            "position_after_quantity": remaining,
            "is_partial_exit": remaining > 0,
            "pnl": proceeds - allocated_cost,
            "pnl_pct": (proceeds / allocated_cost - 1.0) * 100.0,
            "hold_days": day_index - entry["entry_day_index"],
        })
        cash += proceeds
        quantity = remaining
        if quantity == 0:
            entry = None

    for day_index, reference in prices.iterrows():
        date = pd.Timestamp(reference.date).normalize()
        exit_day = False
        if entry is not None:
            code = entry["code"]
            row = daily_maps[code].get(date)
            if row is not None:
                open_price, close_price = float(row.open), float(row.close)
                last_close[code] = close_price
                trend = sorted(set(trend_exit_schedule.get(date, [])))
                if trend:
                    close_position(date, open_price, "trend_exit_" + "_".join(trend), day_index, quantity)
                    exit_day = True
                if entry is not None:
                    warnings = sorted(set(low_momentum_schedule.get(date, [])))
                    if warnings:
                        sell_qty = quantity if len(warnings) >= 2 else min(quantity, entry["buy_quantity"] // 2)
                        suffix = "partial_exit" if quantity > sell_qty else "full_exit"
                        close_position(date, open_price, "momentum_warning_" + "_".join(warnings) + "_" + suffix, day_index, sell_qty)
                        exit_day = entry is None
                if entry is not None:
                    prior_days = candidate_daily[code].loc[candidate_daily[code]["date"] < date]
                    prior_body_low = None if prior_days.empty else min(float(prior_days.iloc[-1].open), float(prior_days.iloc[-1].close))
                    day_bars = bars_maps[code].get(date)
                    if day_bars is None:
                        day_bars = pd.DataFrame([{ "open": open_price, "high": float(row.high), "low": float(row.low), "close": close_price }])
                    for bar in day_bars.itertuples():
                        stop = entry["buy_exec_price"] * (1.0 - stop_loss_pct)
                        thresholds = [(stop, f"stop_loss_{stop_loss_pct * 100:g}pct")] if day_index > entry["entry_day_index"] else []
                        if entry["profit_armed"] and prior_body_low is not None:
                            thresholds.append((prior_body_low, f"profit_trail_body_break_{profit_trail_pct * 100:g}pct"))
                        hit = [item for item in thresholds if float(bar.low) <= item[0]]
                        if hit:
                            threshold, reason = max(hit, key=lambda item: item[0])
                            close_position(date, min(float(bar.open), threshold), reason, day_index, quantity)
                            exit_day = True
                            break
                        if float(bar.high) >= entry["buy_exec_price"] * (1.0 + profit_trail_pct):
                            entry["profit_armed"] = True

        selection = buy_schedule.get(date)
        if selection and (exit_day or entry is not None):
            ignored += 1
        elif selection:
            code = selection["code"]
            row = daily_maps[code].get(date)
            if row is None:
                ignored += 1
            else:
                open_price = float(row.open)
                desired = int(cash / (open_price * 1.002)) // 100 * 100
                while desired > 0:
                    exec_price, cost = calc_buy_cost(open_price, desired, fees)
                    if cost <= cash:
                        break
                    desired -= 100
                if desired > 0:
                    cash -= cost
                    quantity = desired
                    entry = {
                        "code": code, "name": selection["name"], "buy_date": date.strftime("%Y%m%d"),
                        "buy_signal_price": open_price, "buy_exec_price": exec_price, "buy_quantity": quantity,
                        "buy_cost": cost, "buy_signal_type": selection["signal_type"], "entry_day_index": day_index,
                        "profit_armed": False, "position_id": sequence,
                        "selection_type": selection["selection_type"], "rs20": selection["rs20"], "gap10": selection["gap10"],
                    }
                    sequence += 1
                    entry_bars = bars_maps[code].get(date)
                    high = float(entry_bars["high"].max()) if entry_bars is not None else float(row.high)
                    entry["profit_armed"] = high >= exec_price * (1.0 + profit_trail_pct)
                    last_close[code] = float(row.close)

        market_value = quantity * last_close.get(entry["code"], entry["buy_exec_price"]) if entry is not None else 0.0
        nav_rows.append({"date": date, "nav": cash + market_value})

    nav = pd.DataFrame(nav_rows)
    trade_frame = pd.DataFrame(trades)
    if not trade_frame.empty:
        trade_frame = trade_frame.drop(columns=["entry_day_index"])
    return RotationResult(float(nav.iloc[-1].nav), nav, trade_frame, ignored)


def run_research(amv_path: Path, etf_dir: Path, reference_path: Path, output_dir: Path, fees: FeeConfig | None = None) -> pd.DataFrame:
    amv = load_amv_csv(amv_path)
    raw_reference = pd.read_csv(reference_path)
    reference_daily = normalize_etf_history(raw_reference).sort_values("date").reset_index(drop=True)
    reference_intraday = normalize_etf_intraday(raw_reference).sort_values("date").reset_index(drop=True)
    candidate_daily, candidate_intraday = _load_etfs(etf_dir)
    candidate_daily[REFERENCE_ETF] = reference_daily
    candidate_intraday[REFERENCE_ETF] = reference_intraday
    buy_signals = generate_buy_signals(amv)
    buy_signals = buy_signals.loc[buy_signals["signal_type"].isin(["class_2", "class_3"])].reset_index(drop=True)
    trend = generate_trend_exit_signals(amv)
    sell_points, _ = analyze_amv_buy_points(amv)
    trend_schedule = _next_session_schedule(trend, reference_daily["date"], "exit_type")
    low_schedule = _next_session_schedule(sell_points[["date", "sell_momentum_warning_types"]], reference_daily["date"], "sell_momentum_warning_types")
    output_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []
    for universe, common_only in (("common_universe", True), ("dynamic_universe", False)):
        selection_schedule, selections = build_selection_schedule(
            buy_signals, {code: candidate_daily[code] for code in CANDIDATES}, reference_daily, reference_daily["date"], common_only
        )
        selections.to_csv(output_dir / f"selections_{universe}.csv", index=False, encoding="utf-8-sig")
        for stage, (start, end) in scoped_ranges(STAGES).items():
            stage_start = max(pd.Timestamp(start), COMMON_START) if common_only and stage == "train" else pd.Timestamp(start)
            stage_reference = reference_daily.loc[reference_daily["date"].between(stage_start, end)].reset_index(drop=True)
            allowed = set(stage_reference["date"])
            result = run_rotation_backtest(
                stage_reference,
                candidate_daily,
                candidate_intraday,
                {date: item for date, item in selection_schedule.items() if date in allowed},
                {date: kinds for date, kinds in trend_schedule.items() if date in allowed},
                {date: kinds for date, kinds in low_schedule.items() if date in allowed},
                fees=fees,
            )
            metrics = _metrics(result)
            row = {
                "universe": universe, "stage": stage,
                "stage_start": stage_start.strftime("%Y-%m-%d"),
                "entry_signal_count": sum(date in allowed for date in selection_schedule), **metrics,
            }
            summary.append(row)
            result.nav.to_csv(output_dir / f"nav_{universe}_{stage}.csv", index=False, encoding="utf-8-sig")
            result.trades.to_csv(output_dir / f"trades_{universe}_{stage}.csv", index=False, encoding="utf-8-sig")
    output = pd.DataFrame(summary)
    output.to_csv(output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(
        "# 0AMV 买点触发后的行业 ETF 相对强度轮动回测\n\n"
        "买点只采用二类、三类 0AMV 信号。行业ETF须同时满足MA10>MA30、20日收益跑赢510300、且gap10不高于自身历史滚动P80；通过者中选相对强度最高者。没有行业通过时买入510300，次交易日开盘执行。\n\n"
        "共同候选池主样本自 2020-03-05 开始；动态候选池补充结果按各 ETF 实际上市后可用数据计算。卖出规则沿用低动量减仓、MA10<=MA30清仓、5%止损和7%后实体低点止盈。\n\n"
        + output.to_markdown(index=False, floatfmt=".2f") + "\n",
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amv", type=Path, default=Path("data/backtest_data/0AMV-260612.csv"))
    parser.add_argument("--etf-dir", type=Path, default=ETF_DIR)
    parser.add_argument("--reference", type=Path, default=Path("data/backtest_data/510300.SH.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/backtest_runs/etf_kdj_rotation_0amv"))
    args = parser.parse_args()
    print(run_research(args.amv, args.etf_dir, args.reference, args.output).to_string(index=False))


if __name__ == "__main__":
    main()
