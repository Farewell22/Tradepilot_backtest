"""FastAPI 应用 — 回测可视化后端。

启动方式:
    cd /home/wang/workspace/TradePilot2
    ~/python_env/B1_RATE/bin/uvicorn python.backtest_dashboard.api:app \
        --host 0.0.0.0 --port 8082 --reload
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from python.backtest_dashboard import service
from python.backtest_dashboard.schemas import (
    AMVPoint,
    AMVBuyPointResponse,
    AmountRatioRotationResponse,
    EtfAmvSignalResponse,
    EtfKLineResponse,
    IndexPoint,
    NavPoint,
    PositionPoint,
    Rs20EtfRotationResponse,
    RunInfo,
    TradeKLine,
    TradeRow,
    YearlySummary,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="TradePilot2 Backtest Dashboard", version="1.0.0")

# CORS: 允许 Vue dev server (3000) 跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/backtest/runs", response_model=list[RunInfo])
def get_runs():
    """列出所有可用回测。"""
    return service.list_runs()


@app.get("/api/v1/backtest/years/summary", response_model=list[YearlySummary])
def get_years_summary():
    """所有年度汇总指标。"""
    return service.all_summaries()


@app.get("/api/v1/backtest/runs/{run_id}/nav", response_model=list[NavPoint])
def get_nav(run_id: str):
    """单次回测的 NAV 曲线。"""
    try:
        return service.load_nav(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/runs/{run_id}/etf-kline", response_model=EtfKLineResponse)
def get_etf_kline(run_id: str):
    """510300 ETF 日 K 线及成对买卖标记。"""
    try:
        return service.load_etf_kline(run_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/curves/etf-0amv-signals", response_model=EtfAmvSignalResponse)
def get_etf_amv_signals(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
):
    """510300 ETF 日 K 线及按日期对齐的 0AMV 卖点/风险预警。"""
    try:
        return service.load_etf_amv_signals(start_date, end_date)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/curves/etf-ma10-gap-strategy/{stage}", response_model=EtfKLineResponse)
def get_ma10_gap_strategy_kline(stage: str):
    """510300日K及MA10乖离度二、三类组合策略的实际买卖点。"""
    try:
        return service.load_ma10_gap_strategy_kline(stage)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/curves/dividend-low-vol-strategy/{stage}", response_model=EtfKLineResponse)
def get_dividend_low_vol_strategy_kline(stage: str):
    """510880 红利低波 ETF 的 MA10 乖离策略实际买卖点。"""
    try:
        return service.load_dividend_low_vol_strategy_kline(stage)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/curves/amount-ratio-rotation/{stage}", response_model=AmountRatioRotationResponse)
def get_amount_ratio_rotation(stage: str, universe: str = Query("dynamic_universe")):
    """成交额低分位ETF轮动的组合净值、年度统计与交易明细。"""
    try:
        return service.load_amount_ratio_rotation(stage, universe)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/curves/rs20-etf-rotation/{stage}", response_model=Rs20EtfRotationResponse)
def get_rs20_etf_rotation(
    stage: str,
    signal_type: str = Query(..., description="class_2 或 class_3"),
):
    """RS20 Top-1 ETF 轮动的单个买点类别和阶段回测结果。"""
    try:
        return service.load_rs20_etf_rotation(stage, signal_type)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/runs/{run_id}/trades", response_model=list[TradeRow])
def get_trades(
    run_id: str,
    code: str | None = Query(None, description="按股票代码模糊筛选"),
    reason: str | None = Query(None, description="按止损原因模糊筛选"),
    min_pnl_pct: float | None = Query(None),
    max_pnl_pct: float | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """单次回测的交易列表（支持筛选）。"""
    try:
        return service.filter_trades(
            run_id=run_id,
            code=code,
            reason=reason,
            min_pnl_pct=min_pnl_pct,
            max_pnl_pct=max_pnl_pct,
            limit=limit,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/runs/{run_id}/report")
def get_run_report(run_id: str):
    """单次回测的 report 原文 + 结构化指标。"""
    try:
        text = service.load_report_text(run_id)
        metrics = service.parse_report(run_id)
        return {"run_id": run_id, "text": text, "metrics": metrics}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/config")
def get_backtest_config():
    """读取真正生效的评分配置 python/config/stock_rater.yaml。"""
    return service.load_scoring_config()


# ── Run Management ─────────────────────────────────────────

@app.delete("/api/v1/backtest/runs/{run_id}")
def delete_run(run_id: str):
    """删除回测运行。"""
    try:
        service.delete_run(run_id)
        return {"status": "deleted", "run_id": run_id}
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/v1/backtest/runs/{run_id}/rename")
def rename_run(run_id: str, body: dict):
    """重命名回测运行。
    body: {"new_name": "xxx"}
    """
    new_name = body.get("new_name", "")
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name 必填")
    try:
        new_run_id = service.rename_run(run_id, new_name)
        return {"status": "renamed", "old_run_id": run_id, "new_run_id": new_run_id}
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/backtest/runs/{run_id}/meta")
def get_run_meta(run_id: str):
    """读取回测运行的备注信息。"""
    try:
        return service.get_run_meta(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.put("/api/v1/backtest/runs/{run_id}/meta")
def update_run_meta(run_id: str, body: dict):
    """更新回测运行的备注信息。
    body: {"notes": "xxx"}
    """
    notes = body.get("notes", "")
    try:
        return service.update_run_meta(run_id, notes)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/trades/reasons")
def get_all_reasons():
    """所有交易出现过的止损原因（前端筛选用）。"""
    return {"reasons": service.all_reasons()}


@app.get("/api/v1/backtest/trades/{trade_id}/kline", response_model=TradeKLine)
def get_trade_kline(
    trade_id: str,
    range: int = Query(30, ge=5, le=120, description="±多少个交易日"),
):
    """单笔交易的 K 线数据（前range+后range 日 K + 5min 详细）。"""
    try:
        return service.get_trade_kline(trade_id, range_days=range)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.on_event("startup")
def _warm_up():
    """启动时预加载汇总数据，加速首次请求。"""
    logger.info("Warming up cache...")
    runs = service.list_runs()
    logger.info(f"Found {len(runs)} runs")
    for r in runs:
        if not r.has_report:
            continue
        try:
            service.parse_report(r.run_id)
        except Exception as e:
            logger.warning(f"Failed to parse {r.run_id}: {e}")
    logger.info("Warm-up done.")


# ── Curve Overlay APIs ─────────────────────────────────────────

@app.get("/api/v1/backtest/runs/{run_id}/curves/position", response_model=list[PositionPoint])
def get_position_curve(run_id: str):
    """仓位曲线（从 trades.csv 重建）"""
    try:
        return service.reconstruct_position_curve(run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/curves/0amv", response_model=list[AMVPoint])
def get_0amv_curve(
    start_date: str = Query(..., description="开始日期 YYYYMMDD"),
    end_date: str = Query(..., description="结束日期 YYYYMMDD")
):
    """0AMV 活跃市值曲线"""
    return service.load_0amv_curve(start_date, end_date)


@app.get("/api/v1/backtest/curves/0amv/buy-points", response_model=AMVBuyPointResponse)
def get_0amv_buy_points(
    start_date: str | None = Query(None, description="开始日期 YYYYMMDD"),
    end_date: str | None = Query(None, description="结束日期 YYYYMMDD"),
):
    """0AMV 日K、均线、买点和未来收益统计。"""
    try:
        return service.load_0amv_buy_points(start_date, end_date)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/backtest/curves/index", response_model=list[IndexPoint])
def get_index_curve(
    code: str = Query("000001.SH", description="指数代码（000001.SH=上证, 399001.SZ=深证成指）"),
    start_date: str = Query(..., description="开始日期 YYYYMMDD"),
    end_date: str = Query(..., description="结束日期 YYYYMMDD")
):
    """市场指数曲线"""
    return service.load_index_curve(code, start_date, end_date)
