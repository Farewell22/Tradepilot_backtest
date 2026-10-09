"""业务逻辑：读 backtest_runs/ + parquet 数据。"""
from __future__ import annotations

import csv
import logging
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from python.backtest_dashboard.schemas import (
    AmountRatioRotationAnnual,
    AmountRatioRotationResponse,
    AmountRatioRotationSummary,
    AmountRatioRotationTrade,
    Rs20EtfRotationAnnual,
    Rs20EtfRotationResponse,
    Rs20EtfRotationSummary,
    Rs20EtfRotationTrade,
    AMVBuyPoint,
    AMVBuyPointResponse,
    AMVBuyPointSummary,
    DailyBar,
    EtfAmvSignalPoint,
    EtfAmvSignalResponse,
    EtfKLineResponse,
    EtfTradeMarker,
    MinBar,
    NavPoint,
    RunInfo,
    TradeKLine,
    TradeRow,
    YearlySummary,
)
from python.backtest.market_data import normalize_etf_history

logger = logging.getLogger(__name__)

# 项目根目录（python/ 的父目录）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = PROJECT_ROOT / "data" / "backtest_runs"
DATA_DIR = PROJECT_ROOT / "data" / "backtest_data" / "5m_price"
ETF_DATA_PATH = PROJECT_ROOT / "data" / "backtest_data" / "510300.SH.csv"
MA10_GAP_STRATEGY_RUN_DIR = RUNS_DIR / "etf_510300_ma10_above_ma30_gap_signal"
DIVIDEND_LOW_VOL_ETF_DATA_PATH = PROJECT_ROOT / "data" / "backtest_data" / "ETF_60min_2005_2025" / "510880.SH.csv"
DIVIDEND_LOW_VOL_STRATEGY_RUN_DIR = RUNS_DIR / "etf_510880_ma10_above_ma30_gap_signal"
AMOUNT_RATIO_ROTATION_RUN_DIR = RUNS_DIR / "etf_amount_ratio_rotation_0amv"
RS20_ROTATION_RUN_DIR = RUNS_DIR / "etf_rs20_rotation_0amv"

RUN_NAME_PATTERN = re.compile(r"^run_(\d{4})_v\d+$")


# ────────────────────────────────────────────────────────────
# Run discovery
# ────────────────────────────────────────────────────────────

def list_runs_cache_clear():
    """手动清空缓存（保留兼容，现已无缓存，no-op）。"""
    pass


def list_runs() -> list[RunInfo]:
    """扫描 data/backtest_runs/，列出所有回测运行。

    规则：
    - 所有非隐藏目录均为有效回测运行
    - 不按年份去重，全部展示
    - 自动检测 year（从目录名解析第一个 4 位数字）
    """
    out: list[RunInfo] = []
    if not RUNS_DIR.exists():
        return out

    for d in sorted(RUNS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith('.'):
            continue
        # 从目录名解析年份（可选）
        year = 0
        ym = re.search(r'(\d{4})', d.name)
        if ym:
            year = int(ym.group(1))
        out.append(RunInfo(
            run_id=d.name,
            year=year,
            label=f"{d.name} ({year})" if year else d.name,
            path=str(d),
            has_nav=(d / "nav.csv").exists(),
            has_trades=(d / "trades.csv").exists(),
            has_report=(d / "report.txt").exists(),
        ))
        # ETF 按阶段、B1+AMV 按阶段/筛选门槛输出；每个有报告的叶目录独立展示。
        if not (d / "report.txt").exists():
            for stage in sorted(d.iterdir()):
                if not stage.is_dir():
                    continue
                candidates = [stage] if (stage / "report.txt").exists() else [
                    leaf for leaf in sorted(stage.iterdir())
                    if leaf.is_dir() and (leaf / "report.txt").exists()
                ]
                for result_dir in candidates:
                    relative = result_dir.relative_to(d)
                    out.append(RunInfo(
                        run_id=d.name + "__" + "__".join(relative.parts),
                        year=0,
                        label=f"{d.name} / {' / '.join(relative.parts)}",
                        path=str(result_dir),
                        has_nav=(result_dir / "nav.csv").exists(),
                        has_trades=(result_dir / "trades.csv").exists(),
                        has_report=True,
                    ))
    return out


def get_run_path(run_id: str) -> Path:
    """安全获取 run 目录路径，防止路径穿越。"""
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise ValueError(f"Invalid run_id: {run_id}")
    path = RUNS_DIR / run_id
    if not path.exists() and "__" in run_id and RUNS_DIR.exists():
        for parent in sorted(RUNS_DIR.iterdir(), key=lambda item: len(item.name), reverse=True):
            if parent.is_dir() and run_id.startswith(parent.name + "__"):
                child_parts = run_id[len(parent.name) + 2:].split("__")
                if all(child_parts):
                    candidate = parent.joinpath(*child_parts)
                    if candidate.is_dir():
                        path = candidate
                        break
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"Run not found: {run_id}")
    return path


# ────────────────────────────────────────────────────────────
# Yearly summary (parse report.txt)
# ────────────────────────────────────────────────────────────

def parse_report(run_id: str) -> YearlySummary:
    """解析 report.txt 提取汇总指标。"""
    path = get_run_path(run_id) / "report.txt"
    text = path.read_text(encoding="utf-8")

    def extract_float(pattern: str) -> float:
        m = re.search(pattern, text)
        if not m:
            return 0.0
        try:
            return float(m.group(1).replace(",", ""))
        except (ValueError, IndexError):
            return 0.0

    def extract_int(pattern: str) -> int:
        m = re.search(pattern, text)
        if not m:
            return 0
        try:
            return int(m.group(1).replace(",", ""))
        except (ValueError, IndexError):
            return 0

    run_info = next((r for r in list_runs() if r.run_id == run_id), None)
    year = run_info.year if run_info else 0

    return YearlySummary(
        run_id=run_id,
        year=year,
        initial_cash=extract_float(r"初始资金:\s*(-?[\d,]+\.?\d*)"),
        final_nav=extract_float(r"期末净值:\s*(-?[\d,]+\.?\d*)"),
        total_return_pct=extract_float(r"总收益率:\s*(-?[\d,]+\.?\d*)"),
        annualized_return_pct=extract_float(r"年化收益率:\s*(-?[\d,]+\.?\d*)"),
        max_drawdown_pct=extract_float(r"最大回撤:\s*(-?[\d,]+\.?\d*)"),
        sharpe_ratio=extract_float(r"夏普比率:\s*(-?[\d,]+\.?\d*)"),
        n_trades=extract_int(r"交易次数:\s*(-?[\d,]+)"),
        n_wins=extract_int(r"盈利次数:\s*(-?[\d,]+)"),
        n_losses=extract_int(r"亏损次数:\s*(-?[\d,]+)"),
        win_rate_pct=extract_float(r"胜率:\s*(-?[\d,]+\.?\d*)"),
        avg_win_pct=extract_float(r"平均盈利:\s*(-?[\d,]+\.?\d*)"),
        avg_loss_pct=extract_float(r"平均亏损:\s*(-?[\d,]+\.?\d*)"),
        profit_loss_ratio=extract_float(r"盈亏比:\s*(-?[\d,]+\.?\d*)"),
        avg_hold_days=extract_float(r"平均持仓天数:\s*(-?[\d,]+\.?\d*)"),
        n_trading_days=extract_int(r"回测交易日数:\s*(-?[\d,]+)"),
    )


def all_summaries() -> list[YearlySummary]:
    """所有 run 的汇总指标，按年份排序。"""
    return [parse_report(r.run_id) for r in list_runs() if r.has_report]


def load_report_text(run_id: str) -> str:
    """读取 report.txt 原文。"""
    path = get_run_path(run_id) / "report.txt"
    if not path.exists():
        return "(无报告)"
    return path.read_text(encoding="utf-8")


def load_scoring_config() -> dict:
    """读取真正生效的评分配置 python/config/stock_rater.yaml。"""
    from python.scoring.stock_rater import load_config
    return load_config()


# ────────────────────────────────────────────────────────────
# Run management (delete / rename / notes)
# ────────────────────────────────────────────────────────────

def delete_run(run_id: str) -> None:
    """删除回测运行目录（需确认有 report.txt 才允许删除）。"""
    path = get_run_path(run_id)
    if not (path / "report.txt").exists():
        raise ValueError("仅允许删除包含报告的有效回测运行")
    import shutil
    shutil.rmtree(path)


def rename_run(run_id: str, new_name: str) -> str:
    """重命名回测运行目录。

    Args:
        new_name: 新目录名（仅允许字母数字下划线横线）
    Returns:
        新的 run_id
    """
    if not re.match(r'^[\w\-]+$', new_name):
        raise ValueError("目录名仅允许字母、数字、下划线、横线")
    old_path = get_run_path(run_id)
    new_path = RUNS_DIR / new_name
    if new_path.exists():
        raise FileNotFoundError(f"目标目录已存在: {new_name}")
    old_path.rename(new_path)
    return new_name


META_FILE = "meta.json"


def get_run_meta(run_id: str) -> dict:
    """读取回测运行的备注信息。"""
    path = get_run_path(run_id) / META_FILE
    if not path.exists():
        return {"notes": "", "created_at": "", "updated_at": ""}
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def update_run_meta(run_id: str, notes: str) -> dict:
    """更新回测运行的备注信息。"""
    from datetime import datetime
    now = datetime.now().isoformat()
    meta = get_run_meta(run_id)
    if not meta.get("created_at"):
        meta["created_at"] = now
    meta["notes"] = notes
    meta["updated_at"] = now
    import json
    path = get_run_path(run_id) / META_FILE
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


# ────────────────────────────────────────────────────────────
# NAV curve
# ────────────────────────────────────────────────────────────

def load_nav(run_id: str) -> list[NavPoint]:
    path = get_run_path(run_id) / "nav.csv"
    df = pd.read_csv(path, dtype={"date": str})
    out: list[NavPoint] = []
    for _, r in df.iterrows():
        out.append(NavPoint(
            date=str(r["date"]),
            nav=float(r["nav"]),
            return_pct=float(r.get("return_pct", 0.0)),
            drawdown_pct=float(r.get("drawdown_pct", 0.0)),
        ))
    return out


# ────────────────────────────────────────────────────────────
# Trades
# ────────────────────────────────────────────────────────────

def load_trades_raw(run_id: str) -> list[TradeRow]:
    """读 trades.csv，返回全部交易（不过滤）。"""
    path = get_run_path(run_id) / "trades.csv"
    df = pd.read_csv(path, dtype={"buy_date": str, "sell_date": str})
    out: list[TradeRow] = []
    for _, r in df.iterrows():
        buy_date = str(r["buy_date"])
        code = str(r["code"])
        out.append(TradeRow(
            trade_id=f"{run_id}|{buy_date}|{code}",
            run_id=run_id,
            code=code,
            buy_date=buy_date,
            buy_time=str(r.get("buy_time", "")),
            buy_signal_type="" if pd.isna(r.get("buy_signal_type")) else str(r.get("buy_signal_type", "")),
            buy_signal_price=_safe_float(r.get("buy_signal_price")),
            buy_exec_price=_safe_float(r.get("buy_exec_price")),
            buy_quantity=_safe_int(r.get("buy_quantity")),
            buy_cost=_safe_float(r.get("buy_cost")),
            sell_date=str(r.get("sell_date", "")),
            sell_time=str(r.get("sell_time", "")),
            sell_signal_price=_safe_float(r.get("sell_signal_price")),
            sell_exec_price=_safe_float(r.get("sell_exec_price")),
            sell_proceeds=_safe_float(r.get("sell_proceeds")),
            sell_reason=str(r.get("sell_reason", "")),
            pnl=_safe_float(r.get("pnl")),
            pnl_pct=_safe_float(r.get("pnl_pct")),
            hold_days=_safe_int(r.get("hold_days")),
            score=_safe_float(r.get("score")),
        ))
    return out


def load_etf_kline(run_id: str) -> EtfKLineResponse:
    """Load ETF daily candles and pair each trade's buy/sell markers."""
    if not run_id.startswith("etf_510300_0amv__"):
        raise ValueError(f"不是 510300 ETF 回测: {run_id}")
    if not ETF_DATA_PATH.exists():
        raise FileNotFoundError(f"ETF 数据不存在: {ETF_DATA_PATH}")
    nav = load_nav(run_id)
    etf = normalize_etf_history(pd.read_csv(ETF_DATA_PATH))
    if nav:
        start = pd.to_datetime(nav[0].date)
        end = pd.to_datetime(nav[-1].date)
        etf = etf.loc[etf["date"].between(start, end)]
    bars = [
        DailyBar(
            date=row.date.strftime("%Y%m%d"), open=float(row.open), close=float(row.close),
            high=float(row.high), low=float(row.low), vol=float(row.volume), amount=0.0, pct_chg=0.0,
        )
        for row in etf.itertuples()
    ]
    markers = [
        EtfTradeMarker(
            trade_id=trade.trade_id, buy_date=trade.buy_date, sell_date=trade.sell_date,
            buy_price=trade.buy_exec_price, sell_price=trade.sell_exec_price,
            signal_type=trade.buy_signal_type or "unknown", pnl_pct=trade.pnl_pct,
            sell_reason=trade.sell_reason,
        )
        for trade in load_trades_raw(run_id)
    ]
    amv = load_etf_amv_signals(
        bars[0].date if bars else None,
        bars[-1].date if bars else None,
    )
    return EtfKLineResponse(symbol="510300.SH", bars=bars, trades=markers, amv_signals=amv.points)


def _load_ma10_gap_strategy_kline(
    stage: str,
    run_dir: Path,
    etf_path: Path,
    symbol: str,
    marker_prefix: str,
) -> EtfKLineResponse:
    """Load a MA10-gap strategy's ETF candles and actual trade events."""
    if stage not in {"train", "oos"}:
        raise ValueError("阶段必须是 train 或 oos")
    nav_path = run_dir / f"nav_{stage}_class_2_3_combined.csv"
    trades_path = run_dir / f"trades_{stage}_class_2_3_combined.csv"
    if not nav_path.exists() or not trades_path.exists():
        raise FileNotFoundError(f"MA10乖离策略回测结果不存在: {run_dir}")
    if not etf_path.exists():
        raise FileNotFoundError(f"ETF 数据不存在: {etf_path}")

    nav = pd.read_csv(nav_path)
    if nav.empty or "date" not in nav.columns:
        raise ValueError(f"策略净值文件无有效日期: {nav_path}")
    nav_dates = pd.to_datetime(nav["date"], errors="raise")
    etf = normalize_etf_history(pd.read_csv(etf_path))
    etf = etf.loc[etf["date"].between(nav_dates.min(), nav_dates.max())]
    bars = [
        DailyBar(
            date=row.date.strftime("%Y%m%d"), open=float(row.open), close=float(row.close),
            high=float(row.high), low=float(row.low), vol=float(row.volume), amount=0.0, pct_chg=0.0,
        )
        for row in etf.itertuples()
    ]
    trades = pd.read_csv(trades_path)
    markers = [
        EtfTradeMarker(
            trade_id=f"{marker_prefix}__{stage}__{index}",
            buy_date=str(row.buy_date), sell_date=str(row.sell_date),
            buy_price=float(row.buy_exec_price), sell_price=float(row.sell_exec_price),
            signal_type=str(row.buy_signal_type), pnl_pct=float(row.pnl_pct), sell_reason=str(row.sell_reason),
            sell_quantity=int(row.sell_quantity) if "sell_quantity" in trades.columns and pd.notna(row.sell_quantity) else None,
            position_after_quantity=(
                int(row.position_after_quantity)
                if "position_after_quantity" in trades.columns and pd.notna(row.position_after_quantity)
                else None
            ),
            is_partial_exit=(
                bool(row.is_partial_exit)
                if "is_partial_exit" in trades.columns and pd.notna(row.is_partial_exit)
                else False
            ),
        )
        for index, row in trades.iterrows()
    ]
    return EtfKLineResponse(symbol=symbol, bars=bars, trades=markers, amv_signals=[])


def load_ma10_gap_strategy_kline(stage: str) -> EtfKLineResponse:
    """Load 510300 class-2/class-3 MA10-gap strategy results."""
    return _load_ma10_gap_strategy_kline(
        stage, MA10_GAP_STRATEGY_RUN_DIR, ETF_DATA_PATH, "510300.SH", "ma10_gap"
    )


def load_dividend_low_vol_strategy_kline(stage: str) -> EtfKLineResponse:
    """Load 510880 class-2/class-3 MA10-gap strategy results."""
    return _load_ma10_gap_strategy_kline(
        stage,
        DIVIDEND_LOW_VOL_STRATEGY_RUN_DIR,
        DIVIDEND_LOW_VOL_ETF_DATA_PATH,
        "510880.SH",
        "dividend_low_vol",
    )


def load_amount_ratio_rotation(stage: str, universe: str = "dynamic_universe") -> AmountRatioRotationResponse:
    """Load the multi-ETF low-amount-ratio rotation artifacts for one backtest stage."""
    if stage not in {"train", "oos"}:
        raise ValueError("阶段必须是 train 或 oos")
    if universe not in {"dynamic_universe", "common_universe"}:
        raise ValueError("候选池必须是 dynamic_universe 或 common_universe")
    prefix = f"{universe}_{stage}"
    paths = {
        "summary": AMOUNT_RATIO_ROTATION_RUN_DIR / "summary.csv",
        "nav": AMOUNT_RATIO_ROTATION_RUN_DIR / f"nav_{prefix}.csv",
        "annual": AMOUNT_RATIO_ROTATION_RUN_DIR / f"annual_{prefix}.csv",
        "trades": AMOUNT_RATIO_ROTATION_RUN_DIR / f"trades_{prefix}.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"成交额低分位轮动回测结果不存在: {', '.join(missing)}")
    summary_frame = pd.read_csv(paths["summary"])
    summary_rows = summary_frame.loc[(summary_frame["universe"] == universe) & (summary_frame["stage"] == stage)]
    if summary_rows.empty:
        raise ValueError(f"汇总中不存在 {universe}/{stage}")
    summary = AmountRatioRotationSummary(**summary_rows.iloc[0].to_dict())
    nav = [
        NavPoint(date=pd.Timestamp(row.date).strftime("%Y%m%d"), nav=float(row.nav), return_pct=float(row.return_pct), drawdown_pct=float(row.drawdown_pct))
        for row in pd.read_csv(paths["nav"]).itertuples()
    ]
    annual = [AmountRatioRotationAnnual(**row) for row in pd.read_csv(paths["annual"]).to_dict("records")]
    trades = []
    for row in pd.read_csv(paths["trades"], dtype={"buy_date": str, "sell_date": str}).to_dict("records"):
        for column in ("amount_ratio_7_20", "volume_ratio_7_20"):
            if pd.isna(row.get(column)):
                row[column] = None
        row["name"] = "" if pd.isna(row.get("name")) else str(row["name"])
        row["is_partial_exit"] = bool(row.get("is_partial_exit", False))
        trades.append(AmountRatioRotationTrade(**row))
    return AmountRatioRotationResponse(universe=universe, stage=stage, summary=summary, nav=nav, annual=annual, trades=trades)


def load_rs20_etf_rotation(stage: str, signal_type: str) -> Rs20EtfRotationResponse:
    """Load one signal-class and stage of the RS20 ETF rotation artifacts."""
    if stage not in {"train", "oos"}:
        raise ValueError("阶段必须是 train 或 oos")
    if signal_type not in {"class_2", "class_3"}:
        raise ValueError("买点类型必须是 class_2 或 class_3")

    suffix = f"{signal_type}_{stage}"
    paths = {
        "summary": RS20_ROTATION_RUN_DIR / "summary.csv",
        "nav": RS20_ROTATION_RUN_DIR / f"nav_{suffix}.csv",
        "annual": RS20_ROTATION_RUN_DIR / f"annual_{suffix}.csv",
        "trades": RS20_ROTATION_RUN_DIR / f"trades_{suffix}.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"RS20 ETF 选股因子策略回测结果不存在: {', '.join(missing)}")

    summary_rows = pd.read_csv(paths["summary"]).loc[
        lambda frame: (frame["signal_type"] == signal_type) & (frame["stage"] == stage)
    ]
    if summary_rows.empty:
        raise ValueError(f"汇总中不存在 {signal_type}/{stage}")
    summary_data = summary_rows.iloc[0].to_dict()
    # Keep dashboard compatibility with artifacts produced before the field names
    # were aligned with the public RS20 response contract.
    if "ignored_buy_signal_count" not in summary_data and "ignored_buy_signals" in summary_data:
        summary_data["ignored_buy_signal_count"] = summary_data["ignored_buy_signals"]
    if "oos_exit_row_count" not in summary_data and "oos_trade_count" in summary_data:
        summary_data["oos_exit_row_count"] = summary_data["oos_trade_count"]
    if pd.isna(summary_data.get("oos_exit_row_count")):
        summary_data["oos_exit_row_count"] = None
    summary = Rs20EtfRotationSummary(**summary_data)

    nav = [
        NavPoint(
            date=pd.Timestamp(row.date).strftime("%Y%m%d"), nav=float(row.nav),
            return_pct=float(row.return_pct), drawdown_pct=float(row.drawdown_pct),
        )
        for row in pd.read_csv(paths["nav"]).itertuples()
    ]
    annual = [
        Rs20EtfRotationAnnual(**row)
        for row in pd.read_csv(paths["annual"]).to_dict("records")
    ]
    try:
        trade_rows = pd.read_csv(paths["trades"], dtype={"buy_date": str, "sell_date": str}).to_dict("records")
    except pd.errors.EmptyDataError:
        trade_rows = []
    trades = []
    for row in trade_rows:
        if pd.isna(row.get("rs20")):
            row["rs20"] = None
        row["name"] = "" if pd.isna(row.get("name")) else str(row["name"])
        row["is_fallback"] = bool(row.get("is_fallback", False))
        row["is_partial_exit"] = bool(row.get("is_partial_exit", False))
        trades.append(Rs20EtfRotationTrade(**row))
    return Rs20EtfRotationResponse(
        signal_type=signal_type, stage=stage, summary=summary, nav=nav,
        annual=annual, trades=trades,
    )


def load_etf_amv_signals(start_date: str | None = None, end_date: str | None = None) -> EtfAmvSignalResponse:
    """Load daily 510300 ETF candles with date-aligned AMV sell labels."""
    from python.factors.amv_signals import align_amv_sell_signals
    from python.factors.amv_buy_points import analyze_amv_buy_points
    from python.factor_research.data import load_amv_csv

    if not ETF_DATA_PATH.exists():
        raise FileNotFoundError(f"ETF 数据不存在: {ETF_DATA_PATH}")
    raw = pd.read_csv(ETF_DATA_PATH)
    amv_path = PROJECT_ROOT / "data" / "backtest_data" / "0AMV-260612.csv"
    points, _ = analyze_amv_buy_points(load_amv_csv(amv_path))
    annotated = align_amv_sell_signals(raw, points)
    annotated["date"] = pd.to_datetime(annotated["时间"], errors="raise").dt.normalize()
    labels = annotated.groupby("date", as_index=False, sort=True).agg(
        amv_buy_types=("amv_buy_types", "first"),
        amv_sell_types=("amv_sell_types", "first"),
        amv_sell_warning_types=("amv_sell_warning_types", "first"),
        amv_sell_momentum_warning_types=("amv_sell_momentum_warning_types", "first"),
    )
    daily = normalize_etf_history(raw).merge(labels, on="date", how="left")
    daily["amv_sell_types"] = daily["amv_sell_types"].fillna("")
    daily["amv_sell_warning_types"] = daily["amv_sell_warning_types"].fillna("")
    daily["amv_sell_momentum_warning_types"] = daily["amv_sell_momentum_warning_types"].fillna("")
    daily["amv_buy_types"] = daily["amv_buy_types"].fillna("")
    if start_date:
        daily = daily.loc[daily["date"] >= pd.to_datetime(start_date)]
    if end_date:
        daily = daily.loc[daily["date"] <= pd.to_datetime(end_date)]

    def decode(value: object) -> list[str]:
        return [item for item in str(value).split("|") if item]

    return EtfAmvSignalResponse(
        points=[
            EtfAmvSignalPoint(
                date=row.date.strftime("%Y%m%d"), open=float(row.open), close=float(row.close),
                high=float(row.high), low=float(row.low),
                buy_types=decode(row.amv_buy_types),
                sell_types=decode(row.amv_sell_types),
                sell_warning_types=decode(row.amv_sell_warning_types),
                sell_momentum_warning_types=decode(row.amv_sell_momentum_warning_types),
            )
            for row in daily.itertuples()
        ],
        start_date=start_date,
        end_date=end_date,
    )


def filter_trades(
    run_id: str,
    code: str | None = None,
    reason: str | None = None,
    min_pnl_pct: float | None = None,
    max_pnl_pct: float | None = None,
    limit: int = 500,
) -> list[TradeRow]:
    """筛选交易。"""
    rows = load_trades_raw(run_id)
    out = []
    for r in rows:
        if code and code.upper() not in r.code.upper():
            continue
        if reason and reason.lower() not in r.sell_reason.lower():
            continue
        if min_pnl_pct is not None and r.pnl_pct < min_pnl_pct:
            continue
        if max_pnl_pct is not None and r.pnl_pct > max_pnl_pct:
            continue
        out.append(r)
    return out[:limit]


def all_reasons() -> list[str]:
    """所有交易里出现过的止损原因（用于前端筛选器选项）。"""
    reasons: set[str] = set()
    for run in list_runs():
        if not run.has_trades:
            continue
        for t in load_trades_raw(run.run_id):
            if t.sell_reason:
                reasons.add(t.sell_reason)
    return sorted(reasons)


# ────────────────────────────────────────────────────────────
# Trade K-Line (parquet read)
# ────────────────────────────────────────────────────────────

def _safe_float(v) -> float:
    try:
        if pd.isna(v):
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v) -> int:
    try:
        if pd.isna(v):
            return 0
        return int(v)
    except (TypeError, ValueError):
        return 0


def _load_one_day_daily(date_str: str, code: str | None = None) -> pd.DataFrame:
    """读取某个交易日的日线数据，可选按 code 过滤（pyarrow filter pushdown）。

    复用回测时的聚合逻辑（与 data_loader._aggregate_to_daily 保持一致）。
    传 code 时只读该股票的数据，速度提升 100x+。
    """
    year = date_str[:4]
    path = DATA_DIR / year / f"{date_str}.parquet"
    if not path.exists():
        return pd.DataFrame()
    if code:
        df_5min = pq.read_table(path, filters=[("code", "=", code)]).to_pandas()
    else:
        df_5min = pq.read_table(path).to_pandas()
    if df_5min.empty:
        return pd.DataFrame()
    g = df_5min.groupby("code", sort=False)
    import numpy as np
    daily = pd.DataFrame({
        "code": g["code"].first(),
        "date": g["date"].first(),
        "open": g["open"].first(),
        "close": g["close"].last(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "vol": g["vol"].sum(),
        "amount": g["amount"].sum(),
        "pre_close": g["pre_close"].apply(
            lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan
        ),
    }).reset_index(drop=True)
    daily = daily[daily["pre_close"].notna() & (daily["pre_close"] > 0)]
    daily["pct_chg"] = (daily["close"] - daily["pre_close"]) / daily["pre_close"] * 100
    return daily


def _load_one_day_5min(code: str, date_str: str) -> pd.DataFrame:
    """读取某只股票某日的全部 5min bar。"""
    year = date_str[:4]
    path = DATA_DIR / year / f"{date_str}.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pq.read_table(path, filters=[("code", "=", code)]).to_pandas()
    return df.sort_values("trade_time").reset_index(drop=True)


def _list_trading_days_around(center_date: str, before: int, after: int) -> list[str]:
    """获取 center_date 前 before / 后 after 个交易日的日期列表。

    扫描所有 parquet 文件名（与回测口径一致）。
    """
    import glob
    all_files = sorted(glob.glob(str(DATA_DIR / "*" / "*.parquet")))
    all_days = [Path(f).stem for f in all_files]
    try:
        idx = all_days.index(center_date)
    except ValueError:
        return [center_date]
    start = max(0, idx - before)
    end = min(len(all_days), idx + after + 1)
    return all_days[start:end]


@lru_cache(maxsize=128)
def get_trade_kline(trade_id: str, range_days: int = 30) -> TradeKLine:
    """获取单笔交易的 K 线数据。

    Args:
        trade_id: f"{run_id}|{buy_date}|{code}"
        range_days: 买入日前后各多少个交易日
    """
    parts = trade_id.split("|")
    if len(parts) != 3:
        raise ValueError(f"Invalid trade_id: {trade_id}")
    run_id, buy_date, code = parts

    # 从 trades.csv 找这笔交易的元信息
    trades = load_trades_raw(run_id)
    trade = next((t for t in trades if t.buy_date == buy_date and t.code == code), None)
    if trade is None:
        raise FileNotFoundError(f"Trade not found: {trade_id}")

    # 1. 收集 ±range_days 个交易日的日期列表，以 buy_date 为中心
    #    sell_date 可能在 buy_date 之后很多天，要确保 sell_date 也在范围内
    actual_after = range_days
    if trade.sell_date and trade.sell_date > buy_date:
        # 估算卖出日距今多少个交易日（粗略：每个自然月约 21 个交易日）
        # 简单起见，直接用 range_days 但至少能覆盖到 sell_date
        # 这里取 max(range_days, 自然日差)
        from datetime import datetime
        fmt = "%Y%m%d"
        delta_days = (datetime.strptime(trade.sell_date, fmt)
                      - datetime.strptime(buy_date, fmt)).days
        # 自然日 → 大致交易日（×0.7）
        approx_td = int(delta_days * 0.7) + 5
        actual_after = max(range_days, approx_td)

    days_window = _list_trading_days_around(buy_date, range_days, actual_after)

    # 2. 取每天的日线（parquet filter pushdown 到单只股票）
    daily_bars: list[DailyBar] = []
    buy_marker_idx = -1
    sell_marker_idx = -1
    for d in days_window:
        daily_df = _load_one_day_daily(d, code=code)
        if daily_df.empty:
            continue
        row = daily_df[daily_df["code"] == code]
        if row.empty:
            continue
        r = row.iloc[0]
        idx = len(daily_bars)
        daily_bars.append(DailyBar(
            date=str(r["date"]),
            open=float(r["open"]),
            close=float(r["close"]),
            high=float(r["high"]),
            low=float(r["low"]),
            vol=float(r["vol"]),
            amount=float(r["amount"]),
            pct_chg=float(r["pct_chg"]) if not pd.isna(r["pct_chg"]) else 0.0,
        ))
        if d == buy_date:
            buy_marker_idx = idx
        if trade.sell_date and d == trade.sell_date:
            sell_marker_idx = idx

    # 3. 5min 详细图（买入日 + 卖出日）
    buy_5min_df = _load_one_day_5min(code, buy_date)
    buy_5min = [
        MinBar(
            trade_time=str(r["trade_time"]),
            open=float(r["open"]),
            close=float(r["close"]),
            high=float(r["high"]),
            low=float(r["low"]),
            vol=float(r["vol"]),
            amount=float(r["amount"]),
            pct_chg=float(r["pct_chg"]) if not pd.isna(r["pct_chg"]) else 0.0,
        )
        for _, r in buy_5min_df.iterrows()
    ]

    sell_5min: list[MinBar] = []
    if trade.sell_date:
        sell_5min_df = _load_one_day_5min(code, trade.sell_date)
        sell_5min = [
            MinBar(
                trade_time=str(r["trade_time"]),
                open=float(r["open"]),
                close=float(r["close"]),
                high=float(r["high"]),
                low=float(r["low"]),
                vol=float(r["vol"]),
                amount=float(r["amount"]),
                pct_chg=float(r["pct_chg"]) if not pd.isna(r["pct_chg"]) else 0.0,
            )
            for _, r in sell_5min_df.iterrows()
        ]

    return TradeKLine(
        trade_id=trade_id,
        code=code,
        buy_date=buy_date,
        sell_date=trade.sell_date,
        buy_exec_price=trade.buy_exec_price,
        sell_exec_price=trade.sell_exec_price,
        pnl_pct=trade.pnl_pct,
        sell_reason=trade.sell_reason,
        buy_time=trade.buy_time,
        sell_time=trade.sell_time,
        daily=daily_bars,
        buy_5min=buy_5min,
        sell_5min=sell_5min,
        buy_marker_index=buy_marker_idx,
        sell_marker_index=sell_marker_idx,
    )


# ────────────────────────────────────────────────────────────
# 曲线叠加相关功能
# ────────────────────────────────────────────────────────────

def reconstruct_position_curve(run_id: str) -> list:
    """从 trades.csv 重建每日持仓曲线。

    遍历 nav.csv 的每个日期，统计当日持仓数量。
    持仓占比基于持仓数量估算（每只持仓约占总资金的 1/max_positions）。
    """
    from python.backtest_dashboard.schemas import PositionPoint

    trades = load_trades_raw(run_id)
    nav_points = load_nav(run_id)

    position_curve = []
    max_positions = 4  # 与回测引擎一致

    for nav_pt in nav_points:
        current_date = nav_pt.date
        position_count = 0

        for trade in trades:
            # 统计当日持仓：买入日<=当前日期<卖出日
            # 未平仓的 trade.sell_date 为空字符串，使用 "99991231" 代替
            sell_date = trade.sell_date if trade.sell_date else "99991231"
            if trade.buy_date <= current_date < sell_date:
                position_count += 1

        # 估算持仓占比
        position_pct = (position_count / max_positions) * 100

        position_curve.append(PositionPoint(
            date=current_date,
            position_count=position_count,
            position_pct=position_pct
        ))

    return position_curve


def load_0amv_curve(start_date: str, end_date: str) -> list:
    """加载活跃市值（0AMV）数据。

    从 data/backtest_data/0AMV-260612.csv 读取。
    日期格式从 YYYY-MM-DD 转换为 YYYYMMDD。
    """
    from python.backtest_dashboard.schemas import AMVPoint

    # 修正路径：0AMV 文件在 data/backtest_data/ 目录下
    amv_path = PROJECT_ROOT / "data" / "backtest_data" / "0AMV-260612.csv"
    if not amv_path.exists():
        logger.warning(f"0AMV file not found: {amv_path}")
        return []

    df = pd.read_csv(amv_path)
    # 转换日期格式：YYYY-MM-DD → YYYYMMDD
    df["date"] = df["date"].str.replace("-", "").str.replace("/", "")
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    df["pct_change"] = df["close"].pct_change() * 100

    return [
        AMVPoint(
            date=str(row["date"]),
            value=float(row["close"]),
            pct_change=float(row.get("pct_change", 0)) if pd.notna(row.get("pct_change")) else 0.0
        )
        for _, row in df.iterrows()
    ]


def _apply_strategy_buy_signals(
    points: pd.DataFrame,
    strategy_signals: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace legacy display labels with the class-2/class-3 strategy signals."""
    labeled = points.copy()
    visible = strategy_signals.loc[strategy_signals["signal_type"].isin(["class_2", "class_3"])]
    signal_by_date = visible.set_index("date")["signal_type"]
    mapped = labeled["date"].map(signal_by_date)
    labeled["signal_type"] = [str(value) if pd.notna(value) else None for value in mapped]
    summaries: list[dict] = []
    names = {"class_2": "二类买点", "class_3": "三类买点"}
    for signal_type in ("class_2", "class_3"):
        rows = labeled.loc[labeled["signal_type"] == signal_type]
        item: dict[str, object] = {
            "signal_type": signal_type,
            "signal_name": names[signal_type],
            "count": int(len(rows)),
        }
        for horizon in (1, 3, 5, 10):
            values = rows[f"forward_return_{horizon}_pct"].dropna()
            item[f"avg_forward_return_{horizon}_pct"] = float(values.mean()) if not values.empty else None
            item[f"win_rate_{horizon}_pct"] = float((values > 0).mean() * 100) if not values.empty else None
        summaries.append(item)
    return labeled, pd.DataFrame(summaries)


def load_0amv_buy_points(start_date: str | None = None, end_date: str | None = None) -> AMVBuyPointResponse:
    """Load 0AMV OHLC, moving averages, classified signals and outcomes."""
    from python.factors.amv_buy_points import analyze_amv_buy_points
    from python.factor_research.data import load_amv_csv

    amv_path = PROJECT_ROOT / "data" / "backtest_data" / "0AMV-260612.csv"
    if not amv_path.exists():
        raise FileNotFoundError(f"0AMV 文件不存在: {amv_path}")
    amv = load_amv_csv(amv_path)
    points, _ = analyze_amv_buy_points(amv, start_date=start_date, end_date=end_date)
    from python.factors.amv_gap import generate_buy_signals

    strategy_signals = generate_buy_signals(amv).loc[:, ["date", "signal_type"]]
    points, summary = _apply_strategy_buy_signals(points, strategy_signals)

    def optional_float(value):
        return None if pd.isna(value) else float(value)

    point_models = [
        AMVBuyPoint(
            date=row["date"].strftime("%Y%m%d"),
            open=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]),
            ma10=optional_float(row["ma10"]), ma20=optional_float(row["ma20"]),
            momentum_3_pct=optional_float(row["momentum_3"] * 100),
            signal_type=None if pd.isna(row["signal_type"]) else str(row["signal_type"]),
            sell_types=[str(signal_type) for signal_type in row["sell_types"]],
            sell_warning_types=[str(signal_type) for signal_type in row["sell_warning_types"]],
            **{f"forward_return_{horizon}_pct": optional_float(row[f"forward_return_{horizon}_pct"])
               for horizon in (1, 3, 5, 10)},
        )
        for _, row in points.iterrows()
    ]
    summary_models = [
        AMVBuyPointSummary(
            signal_type=row["signal_type"], signal_name=row["signal_name"], count=int(row["count"]),
            **{field: optional_float(row[field]) for field in (
                "avg_forward_return_1_pct", "avg_forward_return_3_pct",
                "avg_forward_return_5_pct", "avg_forward_return_10_pct",
                "win_rate_1_pct", "win_rate_3_pct", "win_rate_5_pct", "win_rate_10_pct",
            )},
        )
        for _, row in summary.iterrows()
    ]
    return AMVBuyPointResponse(
        points=point_models, summary=summary_models,
        start_date=start_date, end_date=end_date,
    )


def load_index_curve(index_code: str, start_date: str, end_date: str) -> list:
    """从 parquet 提取指数日线数据。

    支持的指数代码：
    - 000001.SH: 上证指数
    - 399001.SZ: 深证成指

    返回指定日期范围内的指数收盘价和涨跌幅。
    """
    from python.backtest_dashboard.schemas import IndexPoint

    years = range(int(start_date[:4]), int(end_date[:4]) + 1)
    all_dfs = []

    for year in years:
        year_dir = DATA_DIR / str(year)
        if not year_dir.exists():
            continue
        for file in sorted(year_dir.glob("*.parquet")):
            try:
                df = pq.read_table(file, filters=[("code", "=", index_code)]).to_pandas()
                if not df.empty:
                    all_dfs.append(df)
            except Exception as e:
                logger.debug(f"Failed to read {file} for {index_code}: {e}")
                continue

    if not all_dfs:
        logger.warning(f"No data found for index: {index_code}")
        return []

    full_df = pd.concat(all_dfs, ignore_index=True)

    # 聚合为日线：使用与回测相同的逻辑
    daily = full_df.groupby("date", sort=False).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "pre_close": "first"
    }).reset_index()

    daily["pct_change"] = (daily["close"] - daily["pre_close"]) / daily["pre_close"] * 100
    daily = daily[(daily["date"] >= start_date) & (daily["date"] <= end_date)]

    return [
        IndexPoint(
            date=str(row["date"]),
            close=float(row["close"]),
            pct_change=float(row["pct_change"]) if pd.notna(row["pct_change"]) else 0.0
        )
        for _, row in daily.iterrows()
    ]
