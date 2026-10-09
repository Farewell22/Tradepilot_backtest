"""Pydantic 响应模型。"""
from __future__ import annotations

from pydantic import BaseModel


class RunInfo(BaseModel):
    run_id: str        # 目录名，如 "run_2024_v4"
    year: int          # 年份，如 2024
    label: str         # 显示名，如 "2024"
    path: str          # 绝对路径
    has_nav: bool
    has_trades: bool
    has_report: bool


class YearlySummary(BaseModel):
    run_id: str
    year: int
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
    profit_loss_ratio: float
    avg_hold_days: float
    n_trading_days: int


class NavPoint(BaseModel):
    date: str
    nav: float
    return_pct: float
    drawdown_pct: float


class AmountRatioRotationSummary(BaseModel):
    universe: str
    stage: str
    stage_start: str
    entry_signal_count: int
    fallback_510300_count: int
    final_value: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    closed_trade_count: int
    win_rate_pct: float
    ignored_buy_signals: int


class AmountRatioRotationAnnual(BaseModel):
    year: int
    return_pct: float
    max_drawdown_pct: float
    end_nav: float


class AmountRatioRotationTrade(BaseModel):
    code: str
    name: str
    buy_date: str
    sell_date: str
    buy_signal_type: str
    selection_type: str
    amount_quintile: str
    volume_quintile: str
    amount_ratio_7_20: float | None = None
    volume_ratio_7_20: float | None = None
    pnl_pct: float
    hold_days: int
    sell_reason: str
    is_partial_exit: bool = False


class AmountRatioRotationResponse(BaseModel):
    universe: str
    stage: str
    summary: AmountRatioRotationSummary
    nav: list[NavPoint]
    annual: list[AmountRatioRotationAnnual]
    trades: list[AmountRatioRotationTrade]


class Rs20EtfRotationSummary(BaseModel):
    signal_type: str
    stage: str
    stage_start: str
    stage_end: str
    entry_signal_count: int
    fallback_510300_count: int
    ignored_buy_signal_count: int
    oos_exit_row_count: int | None = None
    final_value: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    closed_trade_count: int
    win_rate_pct: float


class Rs20EtfRotationAnnual(BaseModel):
    year: int
    return_pct: float
    max_drawdown_pct: float
    end_nav: float


class Rs20EtfRotationTrade(BaseModel):
    code: str
    name: str
    buy_date: str
    sell_date: str
    buy_signal_type: str
    selection_type: str
    rs20: float | None = None
    candidate_count: int
    is_fallback: bool
    pnl_pct: float
    hold_days: int
    sell_reason: str
    is_partial_exit: bool = False


class Rs20EtfRotationResponse(BaseModel):
    signal_type: str
    stage: str
    summary: Rs20EtfRotationSummary
    nav: list[NavPoint]
    annual: list[Rs20EtfRotationAnnual]
    trades: list[Rs20EtfRotationTrade]


class TradeRow(BaseModel):
    # 用 (run_id, buy_date, code) 作为复合 ID
    trade_id: str           # f"{run_id}|{buy_date}|{code}"
    run_id: str
    code: str
    buy_date: str
    buy_time: str
    buy_signal_type: str = ""
    buy_signal_price: float
    buy_exec_price: float
    buy_quantity: int
    buy_cost: float
    sell_date: str
    sell_time: str
    sell_signal_price: float
    sell_exec_price: float
    sell_proceeds: float
    sell_reason: str
    pnl: float
    pnl_pct: float
    hold_days: int
    score: float = 0.0


class EtfTradeMarker(BaseModel):
    trade_id: str
    buy_date: str
    sell_date: str
    buy_price: float
    sell_price: float
    signal_type: str
    pnl_pct: float
    sell_reason: str
    sell_quantity: int | None = None
    position_after_quantity: int | None = None
    is_partial_exit: bool = False


class EtfKLineResponse(BaseModel):
    symbol: str
    bars: list[DailyBar]
    trades: list[EtfTradeMarker]
    amv_signals: list[EtfAmvSignalPoint] = []


class EtfAmvSignalPoint(BaseModel):
    date: str
    open: float
    close: float
    high: float
    low: float
    buy_types: list[str]
    sell_types: list[str]
    sell_warning_types: list[str]
    sell_momentum_warning_types: list[str] = []


class EtfAmvSignalResponse(BaseModel):
    points: list[EtfAmvSignalPoint]
    start_date: str | None
    end_date: str | None


class DailyBar(BaseModel):
    date: str
    open: float
    close: float
    high: float
    low: float
    vol: float
    amount: float
    pct_chg: float


class MinBar(BaseModel):
    trade_time: str
    open: float
    close: float
    high: float
    low: float
    vol: float
    amount: float
    pct_chg: float


class TradeKLine(BaseModel):
    trade_id: str
    code: str
    buy_date: str
    sell_date: str
    buy_exec_price: float
    sell_exec_price: float
    pnl_pct: float
    sell_reason: str
    buy_time: str                       # 买入触发时间 (HH:MM:SS)
    sell_time: str                      # 卖出触发时间 (HH:MM:SS)
    daily: list[DailyBar]               # ±range 日 K
    buy_5min: list[MinBar]              # 买入日 5min
    sell_5min: list[MinBar]             # 卖出日 5min
    buy_marker_index: int               # daily 中买入点的索引
    sell_marker_index: int              # daily 中卖出点的索引


# 曲线叠加相关数据模型
class PositionPoint(BaseModel):
    date: str
    position_count: int      # 当日持仓数量
    position_pct: float      # 持仓占比 0-100


class IndexPoint(BaseModel):
    date: str
    close: float
    pct_change: float


class AMVPoint(BaseModel):
    date: str
    value: float
    pct_change: float


class AMVBuyPoint(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    ma10: float | None
    ma20: float | None
    momentum_3_pct: float | None
    signal_type: str | None
    sell_types: list[str]
    sell_warning_types: list[str]
    forward_return_1_pct: float | None
    forward_return_3_pct: float | None
    forward_return_5_pct: float | None
    forward_return_10_pct: float | None


class AMVBuyPointSummary(BaseModel):
    signal_type: str
    signal_name: str
    count: int
    avg_forward_return_1_pct: float | None
    avg_forward_return_3_pct: float | None
    avg_forward_return_5_pct: float | None
    avg_forward_return_10_pct: float | None
    win_rate_1_pct: float | None
    win_rate_3_pct: float | None
    win_rate_5_pct: float | None
    win_rate_10_pct: float | None


class AMVBuyPointResponse(BaseModel):
    points: list[AMVBuyPoint]
    summary: list[AMVBuyPointSummary]
    start_date: str | None
    end_date: str | None
