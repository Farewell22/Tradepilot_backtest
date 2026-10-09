"""Run the classified 0AMV strategy on 510300.SH daily history."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
import subprocess
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

from python.backtest.broker import FeeConfig
from python.strategies.etf_amv.strategy import (
    AmvSignalDetector, EtfPortfolio, normalize_etf_history, normalize_etf_intraday,
)
from python.factors.amv_buy_points import analyze_amv_buy_points
from python.backtest.metrics import compute_metrics
from python.backtest.report import write_report
from python.backtest.simulator import COMMISSION_RATE, SLIPPAGE_RATE, STAMP_DUTY_RATE, TRANSFER_FEE_RATE
from python.factor_research.data import load_amv_csv


logger = logging.getLogger(__name__)
DEFAULT_CONFIG_PATH = Path("python/config/etf_0amv.yaml")


def download_etf_history(symbol: str) -> pd.DataFrame:
    import akshare as ak

    return ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust="")


def load_etf_history(
    path: Path,
    symbol: str,
    start_date: str,
    end_date: str,
    refresh: bool = False,
) -> pd.DataFrame:
    cache = normalize_etf_intraday(pd.read_csv(path)) if path.exists() else None
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    covered = cache is not None and cache["date"].min() <= start and cache["date"].max() >= end
    if covered and not refresh:
        return cache
    try:
        downloaded = normalize_etf_intraday(download_etf_history(symbol))
        if downloaded.empty:
            raise ValueError(f"ETF 下载为空: {symbol}")
        path.parent.mkdir(parents=True, exist_ok=True)
        downloaded.to_csv(path, index=False)
        return downloaded
    except Exception as error:
        if cache is not None and not cache.empty:
            logger.warning("ETF 下载失败，使用缓存 %s: %s", path, error)
            return cache
        raise RuntimeError(f"无法获取 ETF {symbol}: {error}") from error


def load_settings(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        settings = yaml.safe_load(handle) or {}
    required = {"paths", "sample", "strategy"}
    missing = required.difference(settings)
    if missing:
        raise ValueError(f"ETF 回测配置缺少字段: {', '.join(sorted(missing))}")
    settings["symbol"] = str(settings["symbol"])
    return settings


def build_signal_schedule(
    signals: pd.DataFrame,
    etf_dates: list[pd.Timestamp],
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, dict[pd.Timestamp, list[dict]]]:
    """Map recent AMV close signals to the next ETF session within the stage."""
    if len(etf_dates) == 0:
        return pd.DataFrame(), {}
    first_date = pd.Timestamp(etf_dates[0]).normalize()
    last_date = pd.Timestamp(etf_dates[-1]).normalize()
    stage_start = pd.to_datetime(start_date).normalize()
    stage_end = pd.to_datetime(end_date).normalize()
    cutoff = max(first_date, stage_start) - timedelta(days=7)
    signal_rows: list[dict] = []
    signals_by_execution: dict[pd.Timestamp, list[dict]] = {}
    for signal in signals.to_dict("records"):
        signal_date = pd.Timestamp(signal["date"]).normalize()
        if signal_date < cutoff:
            continue
        future_dates = [date for date in etf_dates if date > signal_date]
        if not future_dates:
            continue
        execution_date = pd.Timestamp(future_dates[0]).normalize()
        if execution_date < stage_start or execution_date > stage_end or execution_date > last_date:
            continue
        item = {
            "signal_date": signal_date.strftime("%Y%m%d"),
            "execution_date": execution_date.strftime("%Y%m%d"),
            "signal_type": signal["signal_type"],
            "amv_close": float(signal["close"]),
            "momentum_3": float(signal["momentum_3"]),
        }
        signal_rows.append(item)
        signals_by_execution.setdefault(execution_date, []).append(item)
    return pd.DataFrame(signal_rows), signals_by_execution


def filter_signal_types(signals: pd.DataFrame, enabled_types: set[str]) -> pd.DataFrame:
    """Keep only signal ratings enabled by the active backtest configuration."""
    if not enabled_types:
        return signals.iloc[0:0].copy()
    return signals.loc[signals["signal_type"].isin(enabled_types)].reset_index(drop=True)


def filter_signals_above_ma60(signals: pd.DataFrame, amv: pd.DataFrame) -> pd.DataFrame:
    """Keep signals whose 0AMV close is above its 60-day moving average."""
    history = amv.loc[:, ["date", "close"]].copy()
    history["date"] = pd.to_datetime(history["date"], errors="raise").dt.normalize()
    history["close"] = pd.to_numeric(history["close"], errors="raise")
    history["ma60"] = history["close"].rolling(60).mean()
    eligible = history.loc[history["close"] > history["ma60"], ["date"]]
    return signals.merge(eligible, on="date", how="inner").reset_index(drop=True)


def filter_signals_by_ma10_gap(
    signals: pd.DataFrame,
    amv: pd.DataFrame,
    min_quantile: float | None = None,
    veto_quantile: float | None = None,
) -> pd.DataFrame:
    """Filter signals by prior-history MA10 gap quantiles.

    Quantiles use 750 prior valid observations and are shifted by one day so
    the filter cannot use future information. A veto only applies when MA3 is
    not rising on the signal day.
    """
    if min_quantile is None and veto_quantile is None:
        return signals.reset_index(drop=True)
    if any(q is not None and not 0 < float(q) < 1 for q in (min_quantile, veto_quantile)):
        raise ValueError("MA10 gap 分位数必须在0和1之间")
    history = amv.loc[:, ["date", "close"]].copy()
    history["date"] = pd.to_datetime(history["date"], errors="raise").dt.normalize()
    history["close"] = pd.to_numeric(history["close"], errors="raise")
    history["ma10"] = history["close"].rolling(10).mean()
    history["ma3"] = history["close"].rolling(3).mean()
    history["gap10"] = history["close"] / history["ma10"] - 1
    history["gap10_qmin"] = history["gap10"].rolling(750, min_periods=750).quantile(float(min_quantile or veto_quantile)).shift(1)
    if veto_quantile is not None:
        history["gap10_qveto"] = history["gap10"].rolling(750, min_periods=750).quantile(float(veto_quantile)).shift(1)
    history["ma3_not_rising"] = history["ma3"] <= history["ma3"].shift(1)
    metric_columns = ["date", "gap10", "gap10_qmin", "ma3_not_rising"]
    if veto_quantile is not None:
        metric_columns.append("gap10_qveto")
    enriched = signals.merge(history.loc[:, metric_columns], on="date", how="left", validate="one_to_one")
    if min_quantile is not None:
        enriched = enriched.loc[enriched["gap10"] > enriched["gap10_qmin"]]
    if veto_quantile is not None:
        veto = (enriched["gap10"] > enriched["gap10_qveto"]) & enriched["ma3_not_rising"]
        enriched = enriched.loc[~veto]
    return enriched.loc[:, signals.columns].reset_index(drop=True)


def build_sell_schedule(
    signals: pd.DataFrame,
    etf_dates: list[pd.Timestamp],
    start_date: str,
    end_date: str,
) -> dict[pd.Timestamp, list[str]]:
    """Map 0AMV sell signals to the next ETF session open."""
    if not etf_dates:
        return {}
    first_date = pd.Timestamp(etf_dates[0]).normalize()
    stage_start = pd.to_datetime(start_date).normalize()
    stage_end = pd.to_datetime(end_date).normalize()
    cutoff = max(first_date, stage_start) - timedelta(days=7)
    scheduled: dict[pd.Timestamp, list[str]] = {}
    for signal in signals.to_dict("records"):
        signal_date = pd.Timestamp(signal["date"]).normalize()
        if signal_date < cutoff or not signal.get("sell_types"):
            continue
        future_dates = [date for date in etf_dates if date > signal_date]
        if not future_dates:
            continue
        execution_date = pd.Timestamp(future_dates[0]).normalize()
        if stage_start <= execution_date <= stage_end:
            scheduled.setdefault(execution_date, []).extend(signal["sell_types"])
    return scheduled


def _git_revision() -> str:
    root = Path(__file__).resolve().parents[2]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _run_stage(sample: dict, settings: dict, refresh: bool = False, fees: FeeConfig | None = None) -> tuple[EtfPortfolio, pd.DataFrame]:
    paths = settings["paths"]
    strategy = settings["strategy"]
    etf = load_etf_history(
        Path(paths["etf_csv"]), settings["symbol"], sample["start_date"], sample["end_date"], refresh=refresh
    )
    etf = etf.loc[etf["date"].dt.normalize().between(sample["start_date"], sample["end_date"])].reset_index(drop=True)
    daily_etf = normalize_etf_history(etf)
    amv = load_amv_csv(Path(paths["amv_csv"]))
    signals = AmvSignalDetector().detect(
        amv, momentum_window_days=int(strategy.get("momentum_window_days", 5))
    )
    signals = filter_signals_by_ma10_gap(
        signals,
        amv,
        min_quantile=strategy.get("min_amv_gap10_quantile"),
        veto_quantile=strategy.get("veto_amv_gap10_quantile"),
    )
    if strategy.get("require_amv_above_ma60", False):
        signals = filter_signals_above_ma60(signals, amv)
    sell_points, _ = analyze_amv_buy_points(amv)
    sell_schedule = build_sell_schedule(
        sell_points.loc[:, ["date", "sell_types"]],
        daily_etf["date"].tolist(), sample["start_date"], sample["end_date"],
    )
    enabled_signals = set(strategy.get("enabled_signals", ["best", "secondary", "worst"]))
    signals = filter_signal_types(signals, enabled_signals)
    signal_frame, signals_by_execution = build_signal_schedule(
        signals, daily_etf["date"].tolist(), sample["start_date"], sample["end_date"]
    )

    portfolio = EtfPortfolio(
        initial_cash=float(strategy["initial_cash"]),
        fees=fees,
        target_weights={
            "best": float(strategy["best_weight"]),
            "secondary": float(strategy["secondary_weight"]),
            "worst": float(strategy["worst_weight"]),
        },
        stop_loss={
            "best": float(strategy["best_stop_loss"]),
            "secondary": float(strategy["secondary_stop_loss"]),
            "worst": float(strategy["worst_stop_loss"]),
        },
        max_hold_days={
            "best": int(strategy["best_max_hold_days"]),
            "secondary": int(strategy["secondary_max_hold_days"]),
            "worst": int(strategy.get("worst_max_hold_days", 10)),
        },
        profit_trail_threshold={
            "best": float(strategy["best_profit_trail_threshold"]),
            "secondary": float(strategy["secondary_profit_trail_threshold"]),
            "worst": float(strategy["worst_profit_trail_threshold"]),
        },
    )
    for day_index, row in daily_etf.iterrows():
        session_date = row["date"]
        day_bars = etf.loc[etf["date"].dt.normalize() == session_date]
        sell_types = sell_schedule.get(session_date, [])
        if sell_types and portfolio.position is not None:
            reason = "sell_signal_" + "_".join(sorted(set(sell_types)))
            portfolio.force_sell(
                session_date.strftime("%Y%m%d"), day_index, float(day_bars.iloc[0]["open"]), reason,
            )
            portfolio.process_day_close(session_date.strftime("%Y%m%d"), day_index, float(row["close"]))
            continue
        day_signals = signals_by_execution.get(session_date, [])
        if day_signals:
            strongest = max(day_signals, key=lambda item: {"worst": 1, "secondary": 2, "best": 3}[item["signal_type"]])
            portfolio.apply_signal(strongest["execution_date"], day_index, strongest["signal_type"], float(day_bars.iloc[0]["open"]))
        if day_index > 0 and portfolio.position is not None:
            previous_day = daily_etf.iloc[day_index - 1]
            portfolio.update_daily_take_profit(
                min(float(previous_day["open"]), float(previous_day["close"])),
                float(previous_day["close"]),
            )
        previous_bar = None
        for _, bar in day_bars.iterrows():
            closed = portfolio.process_intraday_bar(
                bar["date"].strftime("%Y%m%d %H:%M"), day_index,
                {"open": float(bar["open"]), "high": float(bar["high"]), "low": float(bar["low"]), "close": float(bar["close"])},
                None,
            )
            if closed is not None:
                break
            previous_bar = bar
        portfolio.process_day_close(session_date.strftime("%Y%m%d"), day_index, float(row["close"]))
    return portfolio, signal_frame


def run_stage(stage_name: str, settings: dict, refresh: bool = False, fees: FeeConfig | None = None) -> Path:
    sample = settings["sample"][stage_name]
    portfolio, signals = _run_stage(sample, settings, refresh=refresh, fees=fees)
    output_dir = Path(settings["paths"]["output_root"])
    output_dir = output_dir / stage_name
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = compute_metrics(portfolio.initial_cash, portfolio.nav_history, portfolio.closed_trades)
    write_report(output_dir, metrics, portfolio.nav_history, portfolio.closed_trades, [portfolio.position.trade] if portfolio.position else [])
    signals.to_csv(output_dir / "signals.csv", index=False)
    metadata = {
        "symbol": settings["symbol"], "stage": stage_name, "sample": sample,
        "strategy": settings["strategy"], "costs": asdict(fees or FeeConfig.stock_legacy()),
        "code_revision": _git_revision(),
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="510300.SH + 0AMV 分级信号回测")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--stage", choices=("all", "train", "oos"), default="all")
    parser.add_argument("--refresh", action="store_true", help="重新下载 ETF 历史数据")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings(args.config)
    stages = ("train", "oos") if args.stage == "all" else (args.stage,)
    for stage in stages:
        logger.info("Running ETF 0AMV stage %s", stage)
        run_stage(stage, settings, refresh=args.refresh)


if __name__ == "__main__":
    main()
