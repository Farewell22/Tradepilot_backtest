"""Compare full-position 0AMV defense in 512890.SH and 601288.SH."""
from __future__ import annotations

import json
import hashlib
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from python.backtest.broker import FeeConfig, calc_buy_cost, calc_sell_proceeds
from python.strategies.amv_winning.runner import (
    CONSOLIDATION_DATE, CONSOLIDATION_RATIO, STOCK_BANK_CODES, _normalize_intraday,
    compute_performance_metrics, generate_amv_signals, run_full_position_backtest,
)


PRIMARY = "512100.SH"
DEFENSIVE_ETF = "512890.SH"
DEFENSIVE_STOCK = "601288.SH"
BANK_TAKE_PROFIT_PCT = 0.08
STOCK_DIVIDENDS_PATH = Path(__file__).with_name("dividends_601288.csv")
DEFENSIVE_ETF_SPLIT_DATE = pd.Timestamp("2021-10-25")


@dataclass
class DefensiveResult:
    nav: pd.DataFrame
    trades: pd.DataFrame
    open_positions: dict[str, int]


def write_code_snapshot(output_dir: Path) -> Path:
    """Keep exact execution sources when the working tree is not committed."""
    project_root = Path(__file__).resolve().parents[3]
    sources = (
        "python/strategies/amv_winning_defensive/runner.py",
        "python/strategies/amv_winning_defensive/prepare_2026.py",
        "python/strategies/amv_winning/runner.py",
        "python/backtest/broker.py",
        "python/scoring/data_source.py",
        "python/task_registry.py",
        "python/run_backtest.py",
    )
    snapshot_dir = output_dir / "code_snapshot"
    checksums = {}
    for source in sources:
        content = (project_root / source).read_bytes()
        target = snapshot_dir / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        checksums[source] = hashlib.sha256(content).hexdigest()
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"sha256": checksums}, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _quantity(price: float, cash: float, fees: FeeConfig) -> int:
    quantity = int(cash / (price * (1 + fees.slippage_rate))) // 100 * 100
    while quantity > 0 and calc_buy_cost(price, quantity, fees)[1] > cash:
        quantity -= 100
    return quantity


def _bank_take_profit_price(quantity: int, buy_cost: float, fees: FeeConfig) -> float:
    """Lowest cent price whose net stock sale proceeds reach 108% of buy cost."""
    fixed_fee_rate = 1 - fees.stamp_duty_rate - fees.transfer_fee_rate
    variable_fee_rate = fixed_fee_rate - fees.commission_rate
    if variable_fee_rate <= 0:
        raise ValueError("股票卖出费用过高，无法计算止盈价格")
    target = buy_cost * (1 + BANK_TAKE_PROFIT_PCT)
    gross = max((target + fees.min_commission) / fixed_fee_rate,
                target / variable_fee_rate)
    price = math.ceil(gross / ((1 - fees.slippage_rate) * quantity) * 100 - 1e-10) / 100
    if calc_sell_proceeds(price, quantity, fees)[1] < target:
        price += 0.01
    return price


def load_dividend_events(path: Path) -> dict[pd.Timestamp, float]:
    frame = pd.read_csv(path)
    required = {"ex_date", "cash_per_share", "source"}
    if not required.issubset(frame.columns):
        raise ValueError(f"分红表缺少列: {sorted(required - set(frame.columns))}")
    dates = pd.to_datetime(frame["ex_date"], errors="raise").dt.normalize()
    amounts = pd.to_numeric(frame["cash_per_share"], errors="raise")
    if dates.duplicated().any() or (amounts <= 0).any() or frame["source"].isna().any():
        raise ValueError("分红表包含重复日期、非正金额或缺少来源")
    return dict(zip(dates, amounts, strict=True))


def run_defensive_backtest(
    primary_bars: pd.DataFrame,
    defensive_bars: pd.DataFrame,
    amv_signals: pd.DataFrame,
    defensive_code: str,
    initial_cash: float = 200_000.0,
    primary_fees: FeeConfig | None = None,
    defensive_fees: FeeConfig | None = None,
    dividends: dict[pd.Timestamp, float] | None = None,
    *, execution_timing: str = "same_close", primary_code: str = PRIMARY,
) -> DefensiveResult:
    """Use same-close legacy fills or opt-in next-open AMV execution.

    A primary intraday stop is sold at the stop bar and leaves cash. Only
    an AMV close exit buys defense. Dividend amounts are per share on ex date.
    """
    if not primary_code or primary_code == defensive_code:
        raise ValueError("主仓代码必须非空且与防守标的不同")
    if defensive_code not in STOCK_BANK_CODES | {DEFENSIVE_ETF}:
        raise ValueError(f"不支持的防守标的: {defensive_code}")
    if initial_cash <= 0:
        raise ValueError("初始资金必须大于 0")
    if execution_timing not in {"same_close", "next_open"}:
        raise ValueError("execution_timing 必须为 same_close 或 next_open")
    primary_fees = primary_fees or FeeConfig.etf_legacy()
    defensive_fees = defensive_fees or (
        FeeConfig.stock_legacy() if defensive_code in STOCK_BANK_CODES else FeeConfig.etf_legacy()
    )
    primary = _normalize_intraday(primary_bars)
    defensive = _normalize_intraday(defensive_bars)
    signals = amv_signals.copy()
    required = {"date", "buy_signal", "exit_ma10", "exit_macd"}
    if not required.issubset(signals.columns):
        raise ValueError(f"0AMV 信号缺少列: {sorted(required - set(signals.columns))}")
    signals["date"] = pd.to_datetime(signals["date"]).dt.normalize()
    if signals["date"].duplicated().any():
        raise ValueError("0AMV 信号存在重复日期")
    signal_map = signals.set_index("date")
    sessions = {
        code: {date: day for date, day in bars.groupby(bars["date"].dt.normalize())}
        for code, bars in ((primary_code, primary), (defensive_code, defensive))
    }
    dates = sorted(set(signal_map.index) & set(sessions[primary_code]) & set(sessions[defensive_code]))
    if not dates:
        raise ValueError("0AMV、主仓和防守标的没有共同交易日")

    cash = float(initial_cash)
    positions: dict[str, dict] = {}
    trade_rows: list[dict] = []
    nav_rows: list[dict] = []
    previous_body_low: float | None = None
    dividend_total = 0.0
    bank_take_profit_locked = False
    pending_signal: pd.Series | None = None
    dividend_map = {pd.Timestamp(date).normalize(): float(amount)
                    for date, amount in (dividends or {}).items()}

    def sell(code: str, date: pd.Timestamp, price: float, reason: str,
             time: str = "15:00", signal_date: pd.Timestamp | None = None) -> None:
        nonlocal cash
        held = positions.pop(code)
        fees = primary_fees if code == primary_code else defensive_fees
        exec_price, proceeds = calc_sell_proceeds(price, held["quantity"], fees)
        cash += proceeds
        trade_rows.append({
            "date": date.strftime("%Y%m%d"), "time": time, "code": code,
            "side": "sell", "quantity": held["quantity"], "signal_price": price,
            "exec_price": exec_price, "cash_flow": proceeds, "reason": reason,
            "dividend_income": held["dividend_income"],
            "pnl": proceeds + held["dividend_income"] - held["buy_cost"],
            "pnl_pct": (proceeds + held["dividend_income"]) / held["buy_cost"] * 100 - 100,
            "hold_sessions": session_index - held["entry_session_index"],
        })
        if "entry_signal_date" in held:
            trade_rows[-1].update(
                signal_date=(signal_date if signal_date is not None else date).strftime("%Y%m%d"),
                entry_signal_date=held["entry_signal_date"], entry_branch=held["entry_branch"],
            )

    def buy(code: str, date: pd.Timestamp, price: float, reason: str,
            time: str = "15:00", signal_date: pd.Timestamp | None = None,
            entry_branch: str = "") -> None:
        nonlocal cash
        fees = primary_fees if code == primary_code else defensive_fees
        quantity = _quantity(price, cash, fees)
        if quantity == 0:
            return
        exec_price, cost = calc_buy_cost(price, quantity, fees)
        cash -= cost
        positions[code] = {
            "quantity": quantity, "buy_cost": cost, "entry_date": date,
            "entry_session_index": session_index, "reference_price": exec_price,
            "profit_armed": False, "dividend_income": 0.0,
            "consolidation_applied": date >= CONSOLIDATION_DATE,
            "defensive_split_applied": date >= DEFENSIVE_ETF_SPLIT_DATE,
        }
        if code in STOCK_BANK_CODES:
            positions[code]["take_profit_price"] = _bank_take_profit_price(quantity, cost, fees)
        trade_rows.append({
            "date": date.strftime("%Y%m%d"), "time": time, "code": code,
            "side": "buy", "quantity": quantity, "signal_price": price,
            "exec_price": exec_price, "cash_flow": -cost, "reason": reason,
        })
        if signal_date is not None:
            positions[code].update(entry_signal_date=signal_date.strftime("%Y%m%d"),
                                   entry_branch=entry_branch)
            trade_rows[-1].update(signal_date=signal_date.strftime("%Y%m%d"),
                                 entry_signal_date=signal_date.strftime("%Y%m%d"),
                                 entry_branch=entry_branch)

    def execute_signal(signal: pd.Series, date: pd.Timestamp,
                       primary_price: float, defensive_price: float, time: str) -> None:
        nonlocal bank_take_profit_locked
        exit_ma10, exit_macd = bool(signal["exit_ma10"]), bool(signal["exit_macd"])
        annotated = execution_timing == "next_open" or "entry_branch" in signal.index
        source_date = signal.name if annotated else None
        if exit_ma10 or exit_macd:
            reason = (
                "amv_close_below_ma10_and_macd_dead_cross" if exit_ma10 and exit_macd
                else "amv_close_below_ma10" if exit_ma10 else "amv_macd_dead_cross"
            )
            if primary_code in positions:
                sell(primary_code, date, primary_price, reason, time, source_date)
            if defensive_code not in positions and not bank_take_profit_locked:
                buy(defensive_code, date, defensive_price, reason, time, source_date)
        elif bool(signal["buy_signal"]):
            if defensive_code in positions:
                sell(defensive_code, date, defensive_price,
                     "amv_buy_signal_rotate_back", time, source_date)
            if primary_code not in positions:
                buy(primary_code, date, primary_price, "amv_buy_signal", time,
                    source_date, str(signal.get("entry_branch", "")))
            if primary_code in positions:
                bank_take_profit_locked = False

    for session_index, date in enumerate(dates):
        day_primary = sessions[primary_code][date].sort_values("date")
        day_defensive = sessions[defensive_code][date].sort_values("date")
        primary_close = float(day_primary.iloc[-1]["close"])
        defensive_close = float(day_defensive.iloc[-1]["close"])
        daily_open = float(day_primary.iloc[0]["open"])
        daily_high = float(day_primary["high"].max())
        if (defensive_code == DEFENSIVE_ETF and defensive_code in positions
                and not positions[defensive_code]["defensive_split_applied"]
                and date >= DEFENSIVE_ETF_SPLIT_DATE):
            positions[defensive_code]["quantity"] *= 2
            positions[defensive_code]["defensive_split_applied"] = True
        if defensive_code in positions and date in dividend_map:
            amount = positions[defensive_code]["quantity"] * dividend_map[date]
            cash += amount
            dividend_total += amount
            positions[defensive_code]["dividend_income"] += amount

        if primary_code in positions:
            held = positions[primary_code]
            if (primary_code == PRIMARY and not held["consolidation_applied"] and held["entry_date"] < CONSOLIDATION_DATE
                    and date >= CONSOLIDATION_DATE):
                held["quantity"] = math.ceil(held["quantity"] * CONSOLIDATION_RATIO)
                held["reference_price"] /= CONSOLIDATION_RATIO
                held["consolidation_applied"] = True
                if previous_body_low is not None:
                    previous_body_low /= CONSOLIDATION_RATIO

        if execution_timing == "next_open" and pending_signal is not None:
            execute_signal(pending_signal, date, daily_open,
                           float(day_defensive.iloc[0]["open"]), "open")

        intraday_exit = ""
        if primary_code in positions and positions[primary_code]["entry_date"] < date:
            held = positions[primary_code]
            stop_level = held["reference_price"] * 0.975
            trail_level = previous_body_low if held["profit_armed"] else None
            for bar in day_primary.to_dict("records"):
                open_price, low_price = float(bar["open"]), float(bar["low"])
                price: float | None = None
                if open_price < stop_level:
                    price, intraday_exit = open_price, "hard_stop_2.5pct"
                elif trail_level is not None and open_price < trail_level:
                    price, intraday_exit = open_price, "profit_trail_body_break_5pct"
                elif trail_level is not None and low_price < trail_level:
                    price, intraday_exit = trail_level, "profit_trail_body_break_5pct"
                elif low_price < stop_level:
                    price, intraday_exit = stop_level, "hard_stop_2.5pct"
                if price is not None:
                    sell(primary_code, date, price, intraday_exit,
                         pd.Timestamp(bar["date"]).strftime("%H:%M"))
                    break

        if (defensive_code in STOCK_BANK_CODES and defensive_code in positions
                and positions[defensive_code]["entry_date"] < date):
            take_profit_price = positions[defensive_code]["take_profit_price"]
            for bar in day_defensive.to_dict("records"):
                open_price, high_price = float(bar["open"]), float(bar["high"])
                if open_price >= take_profit_price or high_price >= take_profit_price:
                    fill_price = open_price if open_price >= take_profit_price else take_profit_price
                    sell(defensive_code, date, fill_price, "bank_take_profit_8pct",
                         pd.Timestamp(bar["date"]).strftime("%H:%M"))
                    bank_take_profit_locked = True
                    break

        signal = signal_map.loc[date]
        if intraday_exit:
            signal = signal.copy()
            signal["buy_signal"] = False
        if execution_timing == "next_open":
            pending_signal = signal.copy()
        else:
            execute_signal(signal, date, primary_close, defensive_close, "15:00")

        if primary_code in positions and positions[primary_code]["entry_date"] < date:
            if daily_high > positions[primary_code]["reference_price"] * 1.05:
                positions[primary_code]["profit_armed"] = True
        nav_rows.append({
            "date": date, "nav": cash + sum(
                held["quantity"] * (primary_close if code == primary_code else defensive_close)
                for code, held in positions.items()),
            "cash": cash, "dividend_income": dividend_total,
            "primary_quantity": positions.get(primary_code, {}).get("quantity", 0),
            "defensive_quantity": positions.get(defensive_code, {}).get("quantity", 0),
            "invested": bool(positions),
        })
        previous_body_low = min(daily_open, primary_close)

    return DefensiveResult(pd.DataFrame(nav_rows), pd.DataFrame(trade_rows),
                           {code: held["quantity"] for code, held in positions.items()})


def load_stock_bars(data_dir: Path, dates: set[pd.Timestamp],
                    code: str = DEFENSIVE_STOCK) -> pd.DataFrame:
    """Read one stock from date-partitioned 5-minute parquet files."""
    parts = []
    for date in sorted(dates):
        path = data_dir / str(date.year) / f"{date:%Y%m%d}.parquet"
        if not path.is_file():
            continue
        table = pq.read_table(path, filters=[("code", "==", code)],
                              columns=["trade_time", "open", "high", "low", "close", "vol"])
        if not table.num_rows:
            continue
        frame = table.to_pandas().rename(columns={"trade_time": "date", "vol": "volume"})
        parts.append(frame)
    if not parts:
        raise ValueError(f"{code} 在所选区间没有 5 分钟行情")
    return _normalize_intraday(pd.concat(parts, ignore_index=True))


def run_research(amv_path: Path, primary_path: Path, defensive_etf_path: Path,
                 stock_data_dir: Path, output_dir: Path, *, start_date: str | None = None,
                 end_date: str | None = None, initial_cash: float = 200_000.0,
                 fees: FeeConfig | None = None,
                 stock_dividends_path: Path = STOCK_DIVIDENDS_PATH) -> dict:
    """Run both defense assets and the original on identical sessions."""
    etf_fees = fees or FeeConfig.etf_legacy()
    stock_fees = FeeConfig.stock_legacy().with_overrides(
        commission_rate=etf_fees.commission_rate,
        min_commission=etf_fees.min_commission,
        slippage_rate=etf_fees.slippage_rate,
    )
    signals = generate_amv_signals(pd.read_csv(amv_path, encoding="utf-8-sig"))
    primary = _normalize_intraday(pd.read_csv(primary_path, encoding="utf-8-sig"))
    defensive_etf = _normalize_intraday(pd.read_csv(defensive_etf_path, encoding="utf-8-sig"))
    shared = set(signals["date"]) & set(primary["date"].dt.normalize())
    if start_date:
        shared = {date for date in shared if date >= pd.to_datetime(start_date, format="%Y%m%d")}
    if end_date:
        shared = {date for date in shared if date <= pd.to_datetime(end_date, format="%Y%m%d")}
    excluded_etf_sessions = sorted(shared - set(defensive_etf["date"].dt.normalize()))
    shared &= set(defensive_etf["date"].dt.normalize())
    stock = load_stock_bars(stock_data_dir, shared)
    excluded_stock_sessions = sorted(shared - set(stock["date"].dt.normalize()))
    shared &= set(stock["date"].dt.normalize())
    if not shared:
        raise ValueError("所选区间没有 0AMV、主仓及两个防守标的的共同交易日")
    dates = sorted(shared)
    signals = signals.loc[signals["date"].isin(shared)].reset_index(drop=True)
    bars = {PRIMARY: primary, DEFENSIVE_ETF: defensive_etf, DEFENSIVE_STOCK: stock}
    bars = {code: frame.loc[frame["date"].dt.normalize().isin(shared)].reset_index(drop=True)
            for code, frame in bars.items()}
    original = run_full_position_backtest(bars[PRIMARY], signals, initial_cash, etf_fees)
    stock_dividends = load_dividend_events(stock_dividends_path)
    results = {
        DEFENSIVE_ETF: run_defensive_backtest(bars[PRIMARY], bars[DEFENSIVE_ETF], signals,
                                               DEFENSIVE_ETF, initial_cash, etf_fees, etf_fees),
        DEFENSIVE_STOCK: run_defensive_backtest(bars[PRIMARY], bars[DEFENSIVE_STOCK], signals,
                                                 DEFENSIVE_STOCK, initial_cash, etf_fees,
                                                 stock_fees, stock_dividends),
    }
    original_metrics = compute_performance_metrics(original.nav, original.trades,
                                                    initial_cash, original.open_position is not None)
    metrics = {"start_date": dates[0].strftime("%Y%m%d"),
               "end_date": dates[-1].strftime("%Y%m%d"), "shared_sessions": len(dates),
               "excluded_etf_sessions": [date.strftime("%Y%m%d") for date in excluded_etf_sessions],
               "excluded_stock_sessions": [date.strftime("%Y%m%d") for date in excluded_stock_sessions],
               "fees": {"etf": asdict(etf_fees), "stock": asdict(stock_fees)},
               "original": original_metrics, "defensive": {}}
    output_dir.mkdir(parents=True, exist_ok=True)
    nav = pd.DataFrame({"date": original.nav["date"], "original_nav": original.nav["nav"]})
    for code, result in results.items():
        sells = result.trades.loc[result.trades["side"] == "sell"] if not result.trades.empty else result.trades
        metrics["defensive"][code] = compute_performance_metrics(
            result.nav, sells, initial_cash, bool(result.open_positions))
        nav[f"{code}_nav"] = result.nav["nav"]
        result.trades.to_csv(output_dir / f"trades_{code}.csv", index=False, encoding="utf-8-sig")
    nav.to_csv(output_dir / "nav.csv", index=False, encoding="utf-8-sig")
    original.trades.to_csv(output_dir / "trades_original.csv", index=False, encoding="utf-8-sig")
    (output_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 0AMV 必胜策略：0AMV 离场后全仓防守", "",
             f"区间：{dates[0].date()} 至 {dates[-1].date()}；共同交易日：{len(dates)}。", "",
             "| 模式 | 总收益 | 年化收益 | 最大回撤 |", "| --- | ---: | ---: | ---: |"]
    for name, m in (("原版现金", original_metrics),
                    ("红利低波 512890", metrics["defensive"][DEFENSIVE_ETF]),
                    ("农业银行 601288", metrics["defensive"][DEFENSIVE_STOCK])):
        lines.append(f"| {name} | {m['total_return_pct']:.2f}% | {m['annualized_return_pct']:.2f}% | {m['max_drawdown_pct']:.2f}% |")
    lines += ["", "仅 0AMV 跌破 MA10 或 MACD 死叉时，卖出 512100 并在当天收盘买入防守标的；",
              "512100 盘中触发 2.5% 硬止损或盈利后的跟踪止盈时，卖出后持现金；若当天另有 0AMV 离场信号，则仍转入防守标的。",
              "农业银行买入后的交易日起，5 分钟最高价达到扣除买卖费用后净价差收益 +8% 时全仓止盈；跳空越过阈值按开盘价卖出。",
              "农业银行止盈后持现金，直到下一次有效 0AMV 买入信号；连续离场信号不重复买入。红利低波 ETF 不设此止盈。",
              "下一次有效进场信号按当天收盘卖出仍持有的防守仓、买回 512100。离场优先。", "",
              f"因红利低波无行情而排除的日期：{', '.join(metrics['excluded_etf_sessions']) or '无'}。",
              f"因农业银行无行情而排除的日期：{', '.join(metrics['excluded_stock_sessions']) or '无'}。",
              "0AMV 日线信号在收盘后才能确认，同日收盘成交是理想化假设。",
              "ETF 与股票分别计佣金、滑点，股票额外计印花税和过户费；均按整百份/股交易。",
              "农业银行仅在除息日前已持仓时按公开分红公告计入每股现金红利；止盈阈值不含分红，卖出时不重复加现金红利；未计个人持股期相关股息税。",
              "512890 于 2021-10-22 的 1:2 份额拆分已计入；现金分红按零处理。",
              "未模拟涨跌停、停牌期间的不可成交和尾盘流动性冲击。",
              "本次运行的执行代码快照与 SHA-256 见 code_snapshot/manifest.json。", ""]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    write_code_snapshot(output_dir)
    return metrics
