"""绩效指标计算。"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from python.backtest.models import Trade


@dataclass
class Metrics:
    initial_cash: float
    final_nav: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    n_trades: int
    n_wins: int
    n_losses: int
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_loss_ratio: float  # 平均盈利 / 平均亏损 的绝对值
    avg_hold_days: float
    n_trading_days: int


def compute_metrics(
    initial_cash: float,
    nav_history: list[tuple[str, float]],
    closed_trades: list[Trade],
) -> Metrics:
    if not nav_history:
        return _empty_metrics(initial_cash)

    nav_df = pd.DataFrame(nav_history, columns=["date", "nav"])
    final_nav = nav_df["nav"].iloc[-1]
    total_return = (final_nav - initial_cash) / initial_cash * 100

    # 年化收益
    n_days = len(nav_df)
    years = max(n_days / 243.0, 1e-9)
    annual_return = ((final_nav / initial_cash) ** (1 / years) - 1) * 100 if final_nav > 0 else -100

    # 最大回撤
    cummax = nav_df["nav"].cummax()
    drawdown = (nav_df["nav"] - cummax) / cummax * 100
    mdd = float(drawdown.min()) if not drawdown.empty else 0.0

    # 夏普比率（基于日度净值变化，假设无风险利率 = 0）
    daily_ret = nav_df["nav"].pct_change().dropna()
    if len(daily_ret) > 1 and daily_ret.std() > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(243))
    else:
        sharpe = 0.0

    # 交易统计
    n_trades = len(closed_trades)
    wins = [t for t in closed_trades if t.pnl > 0]
    losses = [t for t in closed_trades if t.pnl <= 0]
    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = n_wins / n_trades * 100 if n_trades > 0 else 0.0

    avg_win = float(np.mean([t.pnl_pct for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t.pnl_pct for t in losses])) if losses else 0.0
    pl_ratio = abs(avg_win / avg_loss) if avg_loss < 0 else 0.0
    avg_hold = float(np.mean([t.hold_days for t in closed_trades])) if closed_trades else 0.0

    return Metrics(
        initial_cash=initial_cash,
        final_nav=float(final_nav),
        total_return_pct=float(total_return),
        annualized_return_pct=float(annual_return),
        max_drawdown_pct=mdd,
        sharpe_ratio=sharpe,
        n_trades=n_trades,
        n_wins=n_wins,
        n_losses=n_losses,
        win_rate_pct=win_rate,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        profit_loss_ratio=pl_ratio,
        avg_hold_days=avg_hold,
        n_trading_days=n_days,
    )


def _empty_metrics(initial_cash: float) -> Metrics:
    return Metrics(
        initial_cash=initial_cash, final_nav=initial_cash,
        total_return_pct=0.0, annualized_return_pct=0.0,
        max_drawdown_pct=0.0, sharpe_ratio=0.0,
        n_trades=0, n_wins=0, n_losses=0,
        win_rate_pct=0.0, avg_win_pct=0.0, avg_loss_pct=0.0,
        profit_loss_ratio=0.0, avg_hold_days=0.0, n_trading_days=0,
    )
