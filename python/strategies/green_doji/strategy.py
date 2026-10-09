"""歌尔股份 绿色十字星 尾盘买入 回测。

策略：
- 日K出现绿色十字星（阴线 + 实体≤0.5% + 上下影线）
- 尾盘14:50左右买入
- 持仓期间每日盘中监控 ±5% 止盈止损

用法:
    cd /home/wang/workspace/TradePilot_backtest && \
    ~/python_env/B1_RATE/bin/python -m python.strategies.green_doji.strategy \
        --code 002241.SZ \
        --start 20240924 \
        --end 20250626 \
        --budget 100000 \
        --output data/backtest_runs/ge_er_green_doji
"""
from __future__ import annotations

import argparse
import glob
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from python.backtest.broker import FeeConfig
from python.backtest.broker import calc_buy_cost as broker_buy_cost
from python.backtest.broker import calc_sell_proceeds as broker_sell_proceeds

logger = logging.getLogger(__name__)

# ── 交易成本 ──
COMMISSION_RATE = 0.0003
STAMP_DUTY_RATE = 0.001
TRANSFER_FEE_RATE = 0.00001
SLIPPAGE_RATE = 0.001

# ── 默认参数 ──
DATA_DIR = Path("data/backtest_data/5m_price")
BUY_TIME_TARGET = "14:45:00"   # 尾盘买入目标时间（取该bar的close）


# ═══════════════════════════════════════════════════════════════
# 绿色十字星检测
# ═══════════════════════════════════════════════════════════════

def is_green_doji(open_p: float, close: float, high: float, low: float,
                  pre_close: float, body_threshold_pct: float = 0.5) -> bool:
    """判断日K是否为绿色十字星（宽松标准）。

    Args:
        body_threshold_pct: 实体相对前收盘的最大百分比，默认 0.5%
    """
    if close >= open_p:
        return False

    body = abs(close - open_p)
    upper_shadow = high - max(open_p, close)
    lower_shadow = min(open_p, close) - low

    if pre_close <= 0:
        return False

    body_pct = body / pre_close * 100
    return body_pct <= body_threshold_pct and upper_shadow > 0.001 and lower_shadow > 0.001


# ═══════════════════════════════════════════════════════════════
# 成本计算
# ═══════════════════════════════════════════════════════════════

def calc_buy_cost(price: float, quantity: int, fees: FeeConfig | None = None) -> tuple[float, float]:
    """返回 (exec_price, total_cost)。"""
    return broker_buy_cost(price, quantity, fees or FeeConfig.stock_legacy())


def calc_sell_proceeds(price: float, quantity: int, fees: FeeConfig | None = None) -> tuple[float, float]:
    """返回 (exec_price, proceeds)。"""
    return broker_sell_proceeds(price, quantity, fees or FeeConfig.stock_legacy())


# ═══════════════════════════════════════════════════════════════
# 止盈止损监控
# ═══════════════════════════════════════════════════════════════

def check_exit(bars: pd.DataFrame, cost_price: float,
                highest_high: float,
                sl_pct: float = 3.0, trail_pct: float = 3.0,
                days_held: int = 0):
    """遍历当日5min bar，检查是否触发 固定止损 / 移动止盈。

    移动止盈逻辑：
    - 持仓期间追踪最高价（highest_high）
    - trailing stop = highest_high × (1 - trail_pct/100)
    - 当前 low 跌破 trailing stop → 触发卖出，锁定利润
    - 固定止损（成本价 × (1 - sl_pct/100)）作为硬地板

    Returns: ((trigger_time, reason, exec_price), new_highest_high) | None
    """
    if days_held == 0:
        return None, highest_high  # T+0 不触发

    sl_price = cost_price * (1 - sl_pct / 100)
    new_high = highest_high

    for _, bar in bars.iterrows():
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        bar_time = str(bar["trade_time"])

        # 更新最高价
        if bar_high > new_high:
            new_high = bar_high

        # 有效止损价 = max(固定止损, 移动止盈)
        trail_level = new_high * (1 - trail_pct / 100)
        effective_stop = max(sl_price, trail_level)

        if bar_low <= effective_stop:
            # 判断原因：价格从未显著高于成本 → 固定止损
            if effective_stop == sl_price and new_high <= cost_price * 1.01:
                reason = "stop_loss"
            else:
                reason = "trailing_stop"
            exec_signal = max(bar_low, effective_stop)
            return ((bar_time, reason, exec_signal), new_high)

    return None, new_high


# ═══════════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════════

def load_5min_bars(code: str, date: str) -> pd.DataFrame:
    """读取单股某日的全部5min bar。"""
    year = date[:4]
    path = DATA_DIR / year / f"{date}.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pq.read_table(path, filters=[("code", "=", code)]).to_pandas()
    return df.sort_values("trade_time").reset_index(drop=True)


def aggregate_daily(df_5min: pd.DataFrame) -> dict | None:
    """从5min bar聚合日K线。"""
    if df_5min.empty:
        return None
    return {
        "open": float(df_5min["open"].iloc[0]),
        "close": float(df_5min["close"].iloc[-1]),
        "high": float(df_5min["high"].max()),
        "low": float(df_5min["low"].min()),
        "pre_close": float(df_5min["pre_close"].dropna().iloc[0])
                     if df_5min["pre_close"].notna().any() else 0.0,
        "vol": float(df_5min["vol"].sum()),
        "amount": float(df_5min["amount"].sum()),
    }


def scan_trading_days(start: str, end: str) -> list[str]:
    """扫描DATA_DIR下所有交易日，筛选回测区间。"""
    all_files = sorted(glob.glob(str(DATA_DIR / "*" / "*.parquet")))
    days = [Path(f).stem for f in all_files]
    return [d for d in days if start <= d <= end]


def get_tail_buy_price(bars: pd.DataFrame, target_times=("14:50:00", "14:45:00", "14:55:00")):
    """从5min bar中取尾盘买入价格。

    按 target_times 顺序尝试，取第一个存在的 bar 的 close 价。
    """
    for t in target_times:
        mask = bars["trade_time"].str.endswith(t)
        if mask.any():
            return float(bars[mask].iloc[0]["close"])
    # fallback: 最后一条bar的close
    return float(bars["close"].iloc[-1])


# ═══════════════════════════════════════════════════════════════
# 主回测循环
# ═══════════════════════════════════════════════════════════════

@dataclass
class Trade:
    code: str
    buy_date: str
    buy_time: str = ""
    buy_signal_price: float = 0.0
    buy_exec_price: float = 0.0
    buy_quantity: int = 0
    buy_cost: float = 0.0

    # 止盈止损
    cost_price: float = 0.0  # 用于计算±5%
    highest_high: float = 0.0  # 持仓期间最高成交价（移动止盈用）
    days_held: int = 0
    last_close: float = 0.0  # 最新收盘价，NAV估值用
    half_taken: bool = False  # 是否已执行 7% 半仓止盈

    sell_date: str = ""
    sell_time: str = ""
    sell_signal_price: float = 0.0
    sell_exec_price: float = 0.0
    sell_proceeds: float = 0.0
    sell_reason: str = ""

    pnl: float = 0.0
    pnl_pct: float = 0.0
    hold_days: int = 0
    score: float = 0.0  # 保留字段，统一格式


def run_backtest(
    code: str = "002241.SZ",
    start_date: str = "20240924",
    end_date: str = "20250626",
    budget: float = 100_000.0,
    output_dir: str = "data/backtest_runs/ge_er_green_doji",
    sl_pct: float = 3.0,
    trail_pct: float = 3.0,
    tp_partial_pct: float = 7.0,
    body_threshold_pct: float = 0.5,
    fees: FeeConfig | None = None,
) -> None:
    fees = fees or FeeConfig.stock_legacy()
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    trading_days = scan_trading_days(start_date, end_date)
    if not trading_days:
        raise ValueError(f"请求区间 {start_date}—{end_date} 无可用交易日；请检查 {DATA_DIR} 的数据覆盖")
    logger.info(f"回测区间: {start_date} → {end_date}, "
                f"共 {len(trading_days)} 个交易日, 代码={code}, 预算={budget:,.0f}")

    cash = budget
    initial_cash = budget
    current_trade: Trade | None = None
    closed_trades: list[Trade] = []
    nav_history: list[tuple[str, float]] = []
    doji_dates: list[str] = []  # 记录触发十字星的日期

    for date in trading_days:
        bars = load_5min_bars(code, date)
        if bars.empty:
            # 停牌日：沿用前日NAV
            nav = cash
            if current_trade:
                nav += current_trade.buy_quantity * current_trade.last_close
            nav_history.append((date, nav))
            continue

        daily = aggregate_daily(bars)
        if daily is None:
            nav_history.append((date, cash))
            continue

        # ── 1. 有持仓 → 检查止损 / 移动止盈 / 部分止盈 ──
        if current_trade is not None:
            current_trade.days_held += 1
            current_trade.last_close = daily["close"]

            # ── 1a. 检查 7% 部分止盈（未触发过且 T+1 后） ──
            partial_trigger = None
            if (not current_trade.half_taken
                    and current_trade.days_held > 0):
                tp_price = current_trade.cost_price * (1 + tp_partial_pct / 100)
                for _, bar in bars.iterrows():
                    if float(bar["high"]) >= tp_price:
                        partial_trigger = (
                            str(bar["trade_time"]),
                            min(float(bar["high"]), tp_price))
                        break

            # ── 1b. 检查移动止盈 / 固定止损 ──
            trigger, new_high = check_exit(
                bars, current_trade.cost_price,
                current_trade.highest_high,
                sl_pct=sl_pct, trail_pct=trail_pct,
                days_held=current_trade.days_held)
            current_trade.highest_high = new_high

            # ── 1c. 执行部分止盈：卖一半 ──
            if partial_trigger and not current_trade.half_taken:
            # 注意：如果同一天 trailing 先于 partial 触发，partial 会被跳过
            #（partial 不触发时会继续检查 trailing，若 trailing 触发了就直接全平了）
            # 如果 partial 和 trailing 同一天但 partial 先触发，卖一半后继续检查 trailing
                ptime, pprice = partial_trigger
                half_qty = (current_trade.buy_quantity // 2) // 100 * 100
                if half_qty >= 100:
                    sell_exec, proceeds = calc_sell_proceeds(pprice, half_qty, fees)

                    # 记录半仓止盈的交易
                    import copy
                    half_trade = copy.copy(current_trade)
                    half_trade.buy_quantity = half_qty
                    half_trade.buy_cost = (current_trade.buy_cost
                                           * half_qty / current_trade.buy_quantity)
                    half_trade.sell_date = date
                    half_trade.sell_time = ptime
                    half_trade.sell_signal_price = pprice
                    half_trade.sell_exec_price = sell_exec
                    half_trade.sell_proceeds = proceeds
                    half_trade.sell_reason = "half_take_profit"
                    half_trade.pnl = proceeds - half_trade.buy_cost
                    half_trade.pnl_pct = (half_trade.pnl
                                          / half_trade.buy_cost * 100)
                    half_trade.hold_days = _date_diff(
                        current_trade.buy_date, date)
                    closed_trades.append(half_trade)

                    # 更新剩余持仓（成本按比例缩减）
                    remaining = current_trade.buy_quantity - half_qty
                    current_trade.buy_quantity = remaining
                    current_trade.buy_cost *= remaining / (remaining + half_qty)
                    current_trade.half_taken = True
                    cash += proceeds

                    logger.info(f"[{date}] HALF-TP {code} @ {sell_exec:.2f} "
                                f"x{half_qty}, pnl={half_trade.pnl_pct:+.2f}%, "
                                f"remain x{remaining}")

                    # 卖半后，对剩余的 bar 继续检查移动止盈
                    remaining_bars = bars[
                        bars["trade_time"] > ptime
                    ].copy() if ptime else pd.DataFrame()
                    if not remaining_bars.empty:
                        trigger2, new_high2 = check_exit(
                            remaining_bars, current_trade.cost_price,
                            current_trade.highest_high,
                            sl_pct=sl_pct, trail_pct=trail_pct,
                            days_held=current_trade.days_held)
                        if trigger2:
                            trigger = trigger2  # 覆盖，用更晚的触发
                            current_trade.highest_high = new_high2

            # ── 1d. 执行平仓（移动止盈 / 固定止损 / 半仓后再次触发） ──
            if trigger:
                trigger_time, reason, signal_price = trigger
                sell_exec, proceeds = calc_sell_proceeds(
                    signal_price, current_trade.buy_quantity, fees)
                current_trade.sell_date = date
                current_trade.sell_time = trigger_time
                current_trade.sell_signal_price = signal_price
                current_trade.sell_exec_price = sell_exec
                current_trade.sell_proceeds = proceeds
                current_trade.sell_reason = reason
                current_trade.pnl = proceeds - current_trade.buy_cost
                current_trade.pnl_pct = (current_trade.pnl
                                         / current_trade.buy_cost * 100)
                current_trade.hold_days = _date_diff(
                    current_trade.buy_date, date)

                cash += proceeds
                closed_trades.append(current_trade)
                logger.info(f"[{date}] SELL {code} @ {sell_exec:.2f} "
                            f"({reason}), pnl={current_trade.pnl_pct:+.2f}%, "
                            f"high={current_trade.highest_high:.2f}, "
                            f"hold={current_trade.hold_days}d")
                current_trade = None  # 清仓后再允许开新仓

        # ── 2. 无持仓 → 检测绿色十字星并买入 ──
        if current_trade is None:
            d = daily
            if is_green_doji(d["open"], d["close"], d["high"], d["low"],
                            d["pre_close"], body_threshold_pct):
                doji_dates.append(date)
                buy_price = get_tail_buy_price(bars)
                if buy_price <= 0:
                    logger.warning(f"[{date}] 绿色十字星但无法获取尾盘价格，跳过")
                else:
                    # 用可用现金和预算的较小值计算买入股数（避免亏损后现金不足）
                    effective_budget = min(budget, cash)
                    est_cost = buy_price * (1 + fees.slippage_rate) * 1.001  # 粗略估算
                    quantity = int(effective_budget * 0.99 / est_cost)
                    quantity = (quantity // 100) * 100

                    if quantity >= 100:
                        exec_price, cost = calc_buy_cost(buy_price, quantity, fees)
                        if cost <= cash:
                            cash -= cost
                            current_trade = Trade(
                                code=code,
                                buy_date=date,
                                buy_time=f"{date} 14:50:00",
                                buy_signal_price=buy_price,
                                buy_exec_price=exec_price,
                                buy_quantity=quantity,
                                buy_cost=cost,
                                cost_price=exec_price,
                                highest_high=exec_price,
                                days_held=0,
                                last_close=d["close"],
                            )
                            logger.info(f"[{date}] BUY {code} @ {exec_price:.2f} "
                                        f"x{quantity} (十字星, body={abs(d['close']-d['open'])/d['pre_close']*100:.2f}%)")
                        else:
                            logger.warning(f"[{date}] 现金不足: {cash:.0f} < {cost:.0f}")
                    else:
                        logger.warning(f"[{date}] 股价过高无法买入整手: "
                                       f"{buy_price:.2f}, quantity={quantity}")

        # ── 3. 更新 NAV ──
        nav = cash
        if current_trade:
            nav += current_trade.buy_quantity * current_trade.last_close
        nav_history.append((date, nav))

    # ── 输出 ──
    logger.info(f"回测结束: 共 {len(closed_trades)} 笔交易, "
                f"触发十字星 {len(doji_dates)} 次")

    _write_output(out, initial_cash, nav_history, closed_trades,
                  current_trade, doji_dates, code,
                  sl_pct=sl_pct, trail_pct=trail_pct,
                  tp_partial_pct=tp_partial_pct)


# ═══════════════════════════════════════════════════════════════
# 输出文件
# ═══════════════════════════════════════════════════════════════

def _write_output(out: Path, initial_cash: float,
                  nav_history: list[tuple[str, float]],
                  closed_trades: list[Trade],
                  open_trade: Trade | None,
                  doji_dates: list[str],
                  code: str,
                  sl_pct: float = 3.0,
                  trail_pct: float = 3.0,
                  tp_partial_pct: float = 7.0) -> None:
    # 合并所有交易（已平仓 + 可能未平仓）
    all_trades = list(closed_trades)
    if open_trade:
        all_trades.append(open_trade)

    # trades.csv
    if all_trades:
        rows = []
        for t in all_trades:
            rows.append({
                "code": t.code,
                "buy_date": t.buy_date,
                "buy_time": t.buy_time,
                "buy_signal_price": t.buy_signal_price,
                "buy_exec_price": t.buy_exec_price,
                "buy_quantity": t.buy_quantity,
                "buy_cost": t.buy_cost,
                "sell_date": t.sell_date,
                "sell_time": t.sell_time,
                "sell_signal_price": t.sell_signal_price,
                "sell_exec_price": t.sell_exec_price,
                "sell_proceeds": t.sell_proceeds,
                "sell_reason": t.sell_reason,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "hold_days": t.hold_days,
                "score": t.score,
            })
        trades_df = pd.DataFrame(rows)
        trades_df.to_csv(out / "trades.csv", index=False)
    else:
        pd.DataFrame(columns=[
            "code", "buy_date", "buy_time", "buy_signal_price", "buy_exec_price",
            "buy_quantity", "buy_cost", "sell_date", "sell_time", "sell_signal_price",
            "sell_exec_price", "sell_proceeds", "sell_reason", "pnl", "pnl_pct",
            "hold_days", "score",
        ]).to_csv(out / "trades.csv", index=False)

    # nav.csv
    if nav_history:
        nav_df = pd.DataFrame(nav_history, columns=["date", "nav"])
        nav_df["return_pct"] = (nav_df["nav"] / initial_cash - 1) * 100
        nav_df["drawdown_pct"] = (nav_df["nav"] / nav_df["nav"].cummax() - 1) * 100
        nav_df.to_csv(out / "nav.csv", index=False)

    # report.txt
    final_nav = nav_history[-1][1] if nav_history else initial_cash
    total_return = (final_nav / initial_cash - 1) * 100
    wins = [t for t in closed_trades if t.pnl > 0]
    losses = [t for t in closed_trades if t.pnl <= 0]
    win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
    avg_win = (sum(t.pnl_pct for t in wins) / len(wins)
               if wins else 0)
    avg_loss = (sum(t.pnl_pct for t in losses) / len(losses)
                if losses else 0)
    avg_hold = (sum(t.hold_days for t in closed_trades) / len(closed_trades)
                if closed_trades else 0)

    # 盈亏比
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    # 最大回撤
    peak = initial_cash
    max_dd = 0.0
    for _, nav in nav_history:
        peak = max(peak, nav)
        dd = (nav / peak - 1) * 100
        max_dd = min(max_dd, dd)

    # 年化
    if nav_history:
        n_days = len(nav_history)
        ann_return = ((final_nav / initial_cash) ** (252 / n_days) - 1) * 100
    else:
        ann_return = 0.0
        n_days = 0

    lines = [
        "=" * 70,
        "歌尔股份 绿色十字星 回测报告",
        "=" * 70,
        "",
        f"代码:            {code}",
        f"策略:            绿色十字星尾盘买入 + {tp_partial_pct:.0f}%半仓止盈 + {trail_pct:.0f}%移动止盈 / {sl_pct:.0f}%止损",
        f"初始资金:        {initial_cash:>14,.0f} 元",
        f"期末净值:        {final_nav:>14,.0f} 元",
        f"总收益率(含未平仓):{total_return:>14.2f} %",
        f"年化收益率:      {ann_return:>14.2f} %",
        f"最大回撤:        {max_dd:>14.2f} %",
        "",
        f"交易次数:        {len(closed_trades):>14d}",
        f"  盈利次数:      {len(wins):>14d}",
        f"  亏损次数:      {len(losses):>14d}",
        f"  胜率:          {win_rate:>14.2f} %",
        f"  平均盈利:      {avg_win:>14.2f} %",
        f"  平均亏损:      {avg_loss:>14.2f} %",
        f"  盈亏比:        {pl_ratio:>14.2f}",
        f"  平均持仓天数:  {avg_hold:>14.1f}",
        "",
        f"绿色十字星触发:  {len(doji_dates):>14d} 次",
        f"回测交易日数:    {len(nav_history):>14d}",
    ]

    if doji_dates:
        lines.append("")
        lines.append("-" * 70)
        lines.append("十字星触发日期:")
        for d in doji_dates:
            lines.append(f"  {d}")

    if closed_trades:
        lines.append("")
        lines.append("-" * 70)
        lines.append("交易明细:")
        lines.append(f"{'buy_date':<12} {'sell_date':<12} {'reason':<16} {'pnl%':>8} {'hold':>6}")
        for t in closed_trades:
            lines.append(
                f"{t.buy_date:<12} {t.sell_date:<12} "
                f"{t.sell_reason:<16} {t.pnl_pct:>+8.2f} {t.hold_days:>5}d"
            )

    report = "\n".join(lines) + "\n"
    (out / "report.txt").write_text(report, encoding="utf-8")
    print(report)

    logger.info(f"输出已保存到 {out}/")


def _date_diff(d1: str, d2: str) -> int:
    fmt = "%Y%m%d"
    return (datetime.strptime(d2, fmt) - datetime.strptime(d1, fmt)).days


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="绿色十字星尾盘买入回测 (单股专用)")
    parser.add_argument("--code", default="002241.SZ")
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    parser.add_argument("--budget", type=float, default=100_000.0,
                        help="单笔买入预算（元），默认 10w")
    parser.add_argument("--output", type=str,
                        default="data/backtest_runs/ge_er_green_doji")
    parser.add_argument("--trail-pct", type=float, default=3.0,
                        help="移动止盈回撤百分比，默认 3")
    parser.add_argument("--sl-pct", type=float, default=3.0,
                        help="固定止损百分比，默认 3")
    parser.add_argument("--tp-partial-pct", type=float, default=7.0,
                        help="半仓止盈百分比，默认 7")
    parser.add_argument("--body-threshold", type=float, default=0.5,
                        help="十字星实体最大百分比，默认 0.5")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    run_backtest(
        code=args.code,
        start_date=args.start,
        end_date=args.end,
        budget=args.budget,
        output_dir=args.output,
        sl_pct=args.sl_pct,
        trail_pct=args.trail_pct,
        tp_partial_pct=args.tp_partial_pct,
        body_threshold_pct=args.body_threshold,
    )


if __name__ == "__main__":
    main()
