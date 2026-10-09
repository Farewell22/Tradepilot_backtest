"""报告输出。"""
from __future__ import annotations

from dataclasses import asdict, fields
from pathlib import Path

import pandas as pd

from python.backtest.metrics import Metrics
from python.backtest.models import Trade


def write_report(
    output_dir: Path,
    metrics: Metrics,
    nav_history: list[tuple[str, float]],
    closed_trades: list[Trade],
    open_positions: list[Trade] | None = None,
    config_snapshot: dict | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. trades.csv — 包含已平仓 + 未平仓
    all_trades = list(closed_trades) + (open_positions or [])
    if all_trades:
        trades_df = pd.DataFrame([asdict(t) for t in all_trades])
        trades_df.to_csv(output_dir / "trades.csv", index=False)
    else:
        pd.DataFrame(columns=[field.name for field in fields(Trade)]).to_csv(output_dir / "trades.csv", index=False)

    # 2. nav.csv
    if nav_history:
        nav_df = pd.DataFrame(nav_history, columns=["date", "nav"])
        nav_df["return_pct"] = (nav_df["nav"] / metrics.initial_cash - 1) * 100
        nav_df["drawdown_pct"] = (nav_df["nav"] / nav_df["nav"].cummax() - 1) * 100
        nav_df.to_csv(output_dir / "nav.csv", index=False)

    # 3. report.txt
    open_count = len(open_positions) if open_positions else 0
    realized_pnl = sum(t.pnl for t in closed_trades) if closed_trades else 0
    realized_return = (realized_pnl / metrics.initial_cash * 100) if metrics.initial_cash > 0 else 0.0

    lines = [
        "=" * 70,
        "回测报告",
        "=" * 70,
        "",
        f"初始资金:        {metrics.initial_cash:>14,.0f} 元",
        f"期末净值:        {metrics.final_nav:>14,.0f} 元",
        f"总收益率(含未平仓):{metrics.total_return_pct:>14.2f} %",
        f"已实现收益率:    {realized_return:>14.2f} %",
        f"年化收益率:      {metrics.annualized_return_pct:>14.2f} %",
        f"最大回撤:        {metrics.max_drawdown_pct:>14.2f} %",
        f"夏普比率:        {metrics.sharpe_ratio:>14.2f}",
        "",
        f"已平仓次数:      {len(closed_trades):>14d}",
        f"  盈利:          {metrics.n_wins:>14d}",
        f"  亏损:          {metrics.n_losses:>14d}",
        f"  胜率:          {metrics.win_rate_pct:>14.2f} %",
        f"  平均盈利:      {metrics.avg_win_pct:>14.2f} %",
        f"  平均亏损:      {metrics.avg_loss_pct:>14.2f} %",
        f"  盈亏比:        {metrics.profit_loss_ratio:>14.2f}",
        f"  平均持仓天数:  {metrics.avg_hold_days:>14.1f}",
        f"未平仓持仓数:    {open_count:>14d}",
        "",
        f"回测交易日数:    {metrics.n_trading_days:>14d}",
    ]

    # 汇总所有交易（已平仓 + 未平仓），按买入日期排序
    all_trades = list(closed_trades) + (open_positions or [])
    all_trades.sort(key=lambda t: t.buy_date)
    if all_trades:
        lines.append("")
        lines.append("=" * 70)
        lines.append("交易明细 (前 20 笔)")
        lines.append("=" * 70)
        lines.append(f"{'code':<11} {'buy_date':<10} {'sell_date':<10} {'reason':<15} {'pnl%':>8}")
        for t in all_trades[:20]:
            sell_date = t.sell_date if t.sell_date else "未平仓"
            reason = t.sell_reason if t.sell_reason else "持仓中"
            pnl = t.pnl_pct if t.sell_date else 0.0
            lines.append(
                f"{t.code:<11} {t.buy_date:<10} {sell_date:<10} "
                f"{reason:<15} {pnl:>+8.2f}"
            )

    report_text = "\n".join(lines) + "\n"
    (output_dir / "report.txt").write_text(report_text, encoding="utf-8")

    # 打印到 stdout
    print(report_text)
