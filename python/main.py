"""
TradePilot Python Scoring Service

FastAPI service that wraps the existing stock scoring engine.
Go backend calls this service via HTTP for scoring operations.
"""
from datetime import datetime
from typing import List, Optional
import sys
from pathlib import Path

import traceback

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from scoring.stock_rater import RatingResult, KLineRow, rate_stocks_with_klines
from scoring.data_source import create_source_from_global_config
from scoring.industry import get_industry
from scoring.weekly_invest import analyze_batch

# ── FastAPI App ──────────────────────────────────────────────

app = FastAPI(
    title="TradePilot Scoring Service",
    description="Python backend for stock scoring using Z Ge Zhan Fa",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request/Response Models ────────────────────────────────────

class KLineData(BaseModel):
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    turnover: float = 0.0

class StockRequest(BaseModel):
    code: str
    name: str = ""
    klines: List[KLineData]

class ScoreRequest(BaseModel):
    stocks: List[StockRequest]
    config: Optional[dict] = None

class FetchKLineRequest(BaseModel):
    codes: List[str]
    start: str  # Format: YYYYMMDD
    end: str    # Format: YYYYMMDD

class IndustryRequest(BaseModel):
    codes: List[str]

# ── Weekly Invest Models ───────────────────────────────────────

class WIStockCode(BaseModel):
    code: str
    name: str = ""

class WIAnalyzeRequest(BaseModel):
    stocks: List[WIStockCode]
    config: Optional[dict] = None  # 可选配置覆盖

# ── Health Check ───────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": "tradepilot-scoring", "timestamp": datetime.now().isoformat()}

# ── Scoring Endpoint ───────────────────────────────────────────

@app.post("/api/v1/score")
async def score_stocks(req: ScoreRequest):
    """
    Score stocks based on K-line data.

    Expects:
    - stocks: list of {code, name, klines: [{date, open, close, high, low, volume, turnover}]}
    - config: optional scoring config override

    Returns:
    - results: list of {code, scores: {...}, grade, verdict, signal, ...}
    """
    try:
        # Convert request to internal format
        stocks_to_score = []
        for stock_req in req.stocks:
            kline_rows = [
                KLineRow(
                    date=k.date,
                    open=k.open,
                    close=k.close,
                    high=k.high,
                    low=k.low,
                    volume=k.volume
                )
                for k in stock_req.klines
            ]
            stocks_to_score.append({
                "code": stock_req.code,
                "name": stock_req.name,
                "klines": kline_rows
            })

        # Build name lookup from request
        name_map = {s.code: s.name for s in req.stocks}

        # Call scoring engine
        results = rate_stocks_with_klines(stocks_to_score, config=req.config)

        # Convert to response format
        response_results = []
        for r in results:
            response_results.append({
                "code": r.code,
                "name": name_map.get(r.code, ""),
                "scores": {
                    "trend": r.trend,
                    "position": r.position,
                    "volume": r.volume,
                    "abnormal": r.abnormal,
                    "rr_score": r.rr_score,
                    "bonus": r.bonus,
                    "total": r.total,
                },
                "grade": r.grade,
                "verdict": r.verdict,
                "signal_type": r.signal_type,
                "signal_name": r.signal_name,
                "stop": r.stop,
                "target": r.target,
                "rr_ratio": r.rr_ratio,
                "close_price": r.close,
                "change_pct": r.change_pct,
                "vol_ratio": r.vol_ratio,
                "position_pct": r.position_pct,
                "industry": r.industry,
                "sub_industry": r.sub_industry,
                "comment": r.comment,
            })

        return {"results": response_results}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ── K-line Fetch Endpoint ─────────────────────────────────────

@app.post("/api/v1/fetch-kline")
async def fetch_kline(req: FetchKLineRequest):
    """
    Fetch K-line data for given stock codes.

    Returns:
    - data: dict {code: [{date, open, close, high, low, volume, turnover}, ...]}
    """
    try:
        source = create_source_from_global_config()
        results = {}

        for code in req.codes:
            try:
                df = source.fetch_kline(code, req.start, req.end)
                if df is not None and not df.empty:
                    klines = []
                    for _, row in df.iterrows():
                        klines.append({
                            "date": str(row['date'])[:10],
                            "open": float(row['open']),
                            "close": float(row['close']),
                            "high": float(row['high']),
                            "low": float(row['low']),
                            "volume": float(row.get('volume', row.get('vol', 0))),
                            "turnover": float(row.get('amount', 0))
                        })
                    results[code] = klines
            except Exception as e:
                print(f"Error fetching {code}: {e}")
                results[code] = []

        return {"data": results}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ── Industry Info Endpoint ────────────────────────────────────

@app.post("/api/v1/industry")
async def fetch_industry(req: IndustryRequest):
    """
    Fetch industry information for stock codes.

    Returns:
    - data: dict {code: {industry, sub_industry}}
    """
    try:
        results = {}
        for code in req.codes:
            try:
                info = get_industry(code)
                results[code] = {
                    "industry": info.get("industry", ""),
                    "sub_industry": info.get("sub_industry", "")
                }
            except Exception:
                results[code] = {"industry": "", "sub_industry": ""}

        return {"data": results}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ── Weekly Invest Endpoint ────────────────────────────────────

@app.post("/api/v1/wi/analyze")
async def weekly_invest_analyze(req: WIAnalyzeRequest):
    """
    周线定投分析端点。计算KDJ、牛熊转换、黄白线，返回告警级别。
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        source = create_source_from_global_config()

        kline_map = {}
        for stock in req.stocks:
            try:
                from datetime import date
                config = req.config or {}
                fetch_cfg = config.get("fetch", {})
                start = str(fetch_cfg.get("start", "20240101"))
                end = str(fetch_cfg.get("end", "today"))
                if end.lower() == "today":
                    end = date.today().strftime("%Y%m%d")

                df = source.fetch_kline(stock.code, start, end)
                if df is not None and not df.empty:
                    klines = []
                    for _, row in df.iterrows():
                        klines.append({
                            "date": str(row["date"])[:10],
                            "open": float(row["open"]),
                            "close": float(row["close"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "volume": float(row.get("volume", row.get("vol", 0))),
                        })
                    kline_map[stock.code] = klines
            except Exception as e:
                logger.warning("获取 %s K线失败: %s", stock.code, e)

        stocks_data = [{"code": s.code, "name": s.name} for s in req.stocks]
        results = analyze_batch(stocks_data, kline_map, req.config)

        return {"results": results}

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ── Compute ZX Lines Endpoint ─────────────────────────────────

class ComputeZxRequest(BaseModel):
    code: str
    klines: List[KLineData]

@app.post("/api/v1/compute-zx-lines")
async def compute_zx_lines_endpoint(req: ComputeZxRequest):
    """
    计算知行黄白线时间序列。接收已有 K 线，返回对齐的 zxdq/zxdkx 数组。
    复用 scoring/brick_indicator.py:177 的 compute_zx_lines。
    """
    try:
        import pandas as pd
        from scoring.brick_indicator import compute_zx_lines

        df = pd.DataFrame([
            {"date": k.date, "open": k.open, "close": k.close,
             "high": k.high, "low": k.low, "volume": k.volume}
            for k in req.klines
        ])

        zxdq, zxdkx = compute_zx_lines(df)

        def safe_float(v):
            if pd.isna(v):
                return None
            return float(v)

        return {
            "code": req.code,
            "dates": df["date"].tolist(),
            "zxdq": [safe_float(v) for v in zxdq],
            "zxdkx": [safe_float(v) for v in zxdkx],
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ── Score Run History (替代 Go 的 /stock/runs) ─────────────────

from ratings_store import (
    list_runs as rs_list_runs,
    get_run as rs_get_run,
    get_ratings as rs_get_ratings,
    create_run as rs_create_run,
    rename_run as rs_rename_run,
    delete_run as rs_delete_run,
    next_run_id as rs_next_run_id,
)


class CreateRunRequest(BaseModel):
    id: Optional[str] = None
    name: str = ""
    method: str = "b1"
    mode: str = "aggressive"
    stocks: List[StockRequest]
    config: Optional[dict] = None


@app.get("/api/v1/score/runs/next-id")
def score_runs_next_id():
    return {"id": rs_next_run_id()}


@app.get("/api/v1/score/runs")
def score_runs_list(method: Optional[str] = None, mode: Optional[str] = None):
    return {"runs": rs_list_runs(method=method, mode=mode)}


@app.get("/api/v1/score/runs/{run_id}")
def score_runs_get(run_id: str):
    run = rs_get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return {"run": {k: v for k, v in run.items() if k != "ratings"},
            "ratings": run.get("ratings", [])}


@app.post("/api/v1/score/runs")
async def score_runs_create(req: CreateRunRequest):
    try:
        stocks_to_score = []
        for stock_req in req.stocks:
            kline_rows = [
                KLineRow(date=k.date, open=k.open, close=k.close,
                         high=k.high, low=k.low, volume=k.volume)
                for k in stock_req.klines
            ]
            stocks_to_score.append({
                "code": stock_req.code,
                "name": stock_req.name,
                "klines": kline_rows,
            })

        name_map = {s.code: s.name for s in req.stocks}
        results = rate_stocks_with_klines(stocks_to_score, config=req.config)

        ratings = []
        for r in results:
            ratings.append({
                "code": r.code,
                "name": name_map.get(r.code, ""),
                "scores": {
                    "trend": r.trend,
                    "position": r.position,
                    "volume": r.volume,
                    "abnormal": r.abnormal,
                    "rr_score": r.rr_score,
                    "bonus": r.bonus,
                    "total": r.total,
                },
                "grade": r.grade,
                "verdict": r.verdict,
                "signal_type": r.signal_type,
                "signal_name": r.signal_name,
                "stop": r.stop,
                "target": r.target,
                "rr_ratio": r.rr_ratio,
                "close_price": r.close,
                "change_pct": r.change_pct,
                "vol_ratio": r.vol_ratio,
                "position_pct": r.position_pct,
                "industry": r.industry,
                "sub_industry": r.sub_industry,
                "comment": r.comment,
            })

        run_id = req.id or rs_next_run_id()
        run = rs_create_run(
            run_id=run_id,
            name=req.name,
            method=req.method,
            mode=req.mode,
            stocks=[{"code": s.code, "name": s.name} for s in req.stocks],
            ratings=ratings,
        )
        return {"run": {k: v for k, v in run.items() if k != "ratings"},
                "ratings": ratings}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v1/score/runs/{run_id}/rename")
def score_runs_rename(run_id: str, name: str = Query(...)):
    run = rs_rename_run(run_id, name)
    if not run:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return {"run": run}


@app.delete("/api/v1/score/runs/{run_id}")
def score_runs_delete(run_id: str):
    ok = rs_delete_run(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return {"ok": True}


@app.get("/api/v1/score/runs/{run_id}/ratings")
def score_runs_ratings(run_id: str):
    if not rs_get_run(run_id):
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return {"ratings": rs_get_ratings(run_id)}


# ── Stock Rater Config ────────────────────────────────────────

_STOCK_RATER_CONFIG_PATH = Path(__file__).parent / "config" / "stock_rater.yaml"


@app.get("/api/v1/config/stock-rater")
def get_stock_rater_config():
    if not _STOCK_RATER_CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config file not found")
    with _STOCK_RATER_CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return {"config": cfg}


class SaveConfigRequest(BaseModel):
    config: dict


@app.put("/api/v1/config/stock-rater")
def save_stock_rater_config(req: SaveConfigRequest):
    with _STOCK_RATER_CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(req.config, f, allow_unicode=True, sort_keys=False)
    return {"ok": True, "config": req.config}


# ── Main ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
