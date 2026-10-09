"""Compare CSI 2000 and CSI 1000 primaries with identical direct ABC defense."""
from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

import pandas as pd
import yaml

from python.backtest.broker import FeeConfig
from python.run_backtest import ROOT, RunRequest
from python.strategies.amv_winning import runner as original
from python.strategies.amv_winning.bank_comparison import _paired_events
from python.strategies.amv_winning.bank_stock import snapshot_stock_inputs
from python.strategies.amv_winning_defensive.runner import (
    DEFENSIVE_STOCK, load_dividend_events, load_stock_bars, run_defensive_backtest,
)


PRIMARY = "563300.SH"
BASELINE_PRIMARY = "512100.SH"
EVENT_COLUMNS = [
    "date", "time", "code", "side", "quantity", "signal_price", "exec_price",
    "cash_flow", "reason", "dividend_income", "pnl", "pnl_pct", "hold_sessions",
]


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_primary(path: Path, code: str) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    code_column = "代码" if "代码" in frame else "code" if "code" in frame else None
    if code_column and not frame[code_column].eq(code).all():
        raise ValueError(f"主仓输入代码与 {code} 不一致: {path}")
    return original._normalize_intraday(frame)


def run(request: RunRequest) -> Path:
    """Run both variants on all available CSI 2000 sessions in the request window."""
    return run_primary_variant(request, primary_code=PRIMARY, primary_label="中证2000", variant="csi2000")


def run_primary_variant(request: RunRequest, *, primary_code: str,
                        primary_label: str, variant: str,
                        calendar_policy_path: Path | None = None) -> Path:
    """Change only the attack ETF, keeping the same direct-bank defense simulation."""
    settings = yaml.safe_load(request.config_path.read_text(encoding="utf-8"))
    paths = {key: Path(value) if Path(value).is_absolute() else ROOT / value
             for key, value in settings["paths"].items()}
    initial_cash = float(settings.get("initial_cash", 200000))
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("初始资金必须为有限正数")
    start = pd.to_datetime(request.start_date, format="%Y%m%d")
    end = pd.to_datetime(request.end_date, format="%Y%m%d")
    if start > end:
        raise ValueError("开始日期不得晚于结束日期")
    if request.execution_mode != "legacy_same_close_idealized":
        raise ValueError("本策略保留 legacy_same_close_idealized 成交口径")

    primary = _read_primary(paths["primary_csv"], primary_code)
    primary = primary.loc[primary.date.dt.normalize().between(start, end)].reset_index(drop=True)
    if primary.empty:
        raise ValueError(f"请求区间没有{primary_label} ETF主仓行情")
    first = primary.date.dt.normalize().min()
    last = primary.date.dt.normalize().max()
    baseline = _read_primary(paths["baseline_primary_csv"], BASELINE_PRIMARY)
    baseline = baseline.loc[baseline.date.dt.normalize().between(first, last)].reset_index(drop=True)
    # Indicators retain the entire past history before the trading window is selected.
    signals = original.generate_amv_signals(pd.read_csv(paths["amv_csv"], encoding="utf-8-sig"))
    signals = signals.loc[signals.date.between(first, last)].reset_index(drop=True)
    # A union catches an interior gap in any input instead of silently shortening the calendar.
    dates = set(primary.date.dt.normalize()) | set(baseline.date.dt.normalize()) | set(signals.date)
    calendar_policy = (json.loads(calendar_policy_path.read_text(encoding="utf-8"))
                       if calendar_policy_path is not None else {})
    excluded_sessions, excluded_zero_volume_bars = [], []
    primary_frames = {primary_code: primary, BASELINE_PRIMARY: baseline}
    for event in calendar_policy.get("suspensions", []):
        code, date = event["code"], pd.Timestamp(event["date"]).normalize()
        if code not in primary_frames or not event.get("reason") or not event.get("source"):
            raise ValueError("停牌审计记录必须含当前主仓代码、原因与公告来源")
        if date not in dates:
            continue
        if date in set(primary_frames[code].date.dt.normalize()):
            raise ValueError(f"{code} {date:%Y%m%d}停牌记录与有成交行情冲突")
        dates.remove(date)
        excluded_sessions.append(event)
    if not dates:
        raise ValueError("处理已核实停牌后没有共同交易日")
    first, last = min(dates), max(dates)
    primary = primary.loc[primary.date.dt.normalize().isin(dates)].reset_index(drop=True)
    baseline = baseline.loc[baseline.date.dt.normalize().isin(dates)].reset_index(drop=True)
    signals = signals.loc[signals.date.isin(dates)].reset_index(drop=True)
    if calendar_policy.get("drop_zero_volume_intraday_bars", False):
        for code, frame in ((primary_code, primary), (BASELINE_PRIMARY, baseline)):
            excluded_zero_volume_bars.extend(
                {"code": code, "timestamp": stamp.isoformat()}
                for stamp in frame.loc[frame.volume.eq(0), "date"]
            )
        primary = primary.loc[primary.volume.gt(0)].reset_index(drop=True)
        baseline = baseline.loc[baseline.volume.gt(0)].reset_index(drop=True)
    stock = load_stock_bars(paths["stock_5m_dir"], dates)
    for label, frame, daily in ((primary_code, primary, False), (BASELINE_PRIMARY, baseline, False),
                                ("0AMV", signals, True), (DEFENSIVE_STOCK, stock, False)):
        available = set(frame.date if daily else frame.date.dt.normalize())
        missing = sorted(dates - available)
        if missing:
            raise ValueError(f"{label}缺少交易日: {[day.strftime('%Y%m%d') for day in missing[:10]]}")

    dividends = load_dividend_events(paths["stock_dividends_csv"])
    stock_fees = FeeConfig.stock_legacy().with_overrides(
        commission_rate=request.fees.commission_rate, min_commission=request.fees.min_commission,
        slippage_rate=request.fees.slippage_rate,
    )
    output = request.output_dir
    output.mkdir(parents=True, exist_ok=True)
    results, metrics, annuals = {}, {}, []
    for name, code, frame in ((variant, primary_code, primary), ("baseline", BASELINE_PRIMARY, baseline)):
        result = run_defensive_backtest(
            frame, stock, signals, DEFENSIVE_STOCK, initial_cash, request.fees, stock_fees,
            dividends, primary_code=code,
        )
        events = result.trades.reindex(columns=EVENT_COLUMNS)
        pairs = _paired_events(events, request.fees, stock_fees, primary_code=code)
        nav = result.nav.copy()
        nav["return_pct"] = (nav.nav / initial_cash - 1) * 100
        nav["drawdown_pct"] = (nav.nav / nav.nav.cummax().clip(lower=initial_cash) - 1) * 100
        nav["position_code"] = "cash"
        nav.loc[nav.primary_quantity > 0, "position_code"] = code
        nav.loc[nav.defensive_quantity > 0, "position_code"] = DEFENSIVE_STOCK
        target = output if name == variant else output / "baseline"
        target.mkdir(exist_ok=True)
        nav.to_csv(target / "nav.csv", index=False, encoding="utf-8-sig")
        events.to_csv(target / "trades.csv", index=False, encoding="utf-8-sig")
        pairs.to_csv(target / "paired_trades.csv", index=False, encoding="utf-8-sig")
        signals.to_csv(target / "amv_signals.csv", index=False, encoding="utf-8-sig")
        m = original.compute_performance_metrics(nav, pairs, initial_cash, bool(result.open_positions))
        m.update(
            primary_code=code, bank_code=DEFENSIVE_STOCK,
            requested_start=request.start_date, requested_end=request.end_date,
            actual_start=nav.date.iloc[0].strftime("%Y%m%d"),
            actual_end=nav.date.iloc[-1].strftime("%Y%m%d"), sessions=len(nav),
            dividend_income=float(nav.dividend_income.iloc[-1]), open_positions=result.open_positions,
            execution_mode=request.execution_mode, source_strategy="amv_winning_defensive",
            excluded_sessions=[event["date"] for event in excluded_sessions],
            fees={"primary": asdict(request.fees), "stock": asdict(stock_fees)},
            parameters={"single_day_threshold": .04, "multi_day_sessions": 2,
                        "multi_day_threshold": .04, "entry_ma5": True,
                        "primary_hard_stop_pct": .025, "profit_trail_arming_pct": .05,
                        "bank_take_profit": "8pct_net_price_pnl_excluding_dividends",
                        "bank_stop_loss": None, "post_take_profit": "cash_until_primary_entry"},
        )
        _write_json(target / "metrics.json", m)
        results[name], metrics[name] = nav, m
        annuals.append(original._annual_returns(nav, initial_cash, f"{name}_return_pct"))
    annual = annuals[0].merge(annuals[1], on="year", validate="one_to_one")
    annual.to_csv(output / "annual_returns.csv", index=False, encoding="utf-8-sig")
    comparison = results[variant][["date", "nav"]].merge(
        results["baseline"][["date", "nav"]], on="date", suffixes=(f"_{variant}", "_baseline"),
        validate="one_to_one",
    )
    comparison.to_csv(output / "comparison_nav.csv", index=False, encoding="utf-8-sig")
    _write_json(output / "verification.json", {
        "calendar_identical": results[variant].date.equals(results["baseline"].date),
        "sessions": len(dates), "only_rule_change": "primary_code", "initial_positions": {},
        "excluded_sessions": [event["date"] for event in excluded_sessions],
    })
    _write_json(output / "calendar_audit.json", {
        "policy": calendar_policy.get("policy", "strict_complete_sessions"),
        "sessions": len(dates), "excluded_sessions": excluded_sessions,
        "excluded_zero_volume_bars": excluded_zero_volume_bars,
        "amv_warmup": "full_history_before_calendar_filter",
    })
    lines = [
        f"# {primary_label} ETF＋农业银行直接防守回测", "",
        f"请求区间 {request.start_date}—{request.end_date}；实际区间 {first:%Y%m%d}—{last:%Y%m%d}；"
        f"{len(dates)}个交易日；两组各从 {initial_cash:,.0f} 元现金、无持仓开始。", "",
        f"唯一交易规则差异是进攻主仓：新版{primary_code}，对照512100.SH；防守均为601288.SH。", "",
        "| 方案 | 期末资金 | 总收益 | 年化收益 | 最大回撤 | 夏普 | 胜率 | 已平仓交易 | 税前分红 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, label in (("baseline", "中证1000＋农行"), (variant, f"{primary_label}＋农行")):
        m = metrics[name]
        lines.append(
            f"| {label} | {m['final_nav']:,.2f} | {m['total_return_pct']:.2f}% | "
            f"{m['annualized_return_pct']:.2f}% | {m['max_drawdown_pct']:.2f}% | "
            f"{m['sharpe_ratio']:.3f} | {m['win_rate_pct']:.2f}% | "
            f"{m['closed_trade_count']} | {m['dividend_income']:,.2f} |"
        )
    lines += ["", "## 年度收益", "", "首年为实际起点至年末，其后相对上年末净值。", "",
              f"| 年份 | 中证1000＋农行 | {primary_label}＋农行 |", "|---|---:|---:|"]
    for row in annual.to_dict("records"):
        lines.append(f"| {row['year']} | {row['baseline_return_pct']:.2f}% | {row[f'{variant}_return_pct']:.2f}% |")
    lines += [
        "", "## 规则、费用与可比范围", "",
        "0AMV单日或两日累计涨幅≥4%且收盘≥MA5进主仓；收盘低于MA10或MACD死叉转农行；离场优先。",
        "主仓2.5%硬止损；买入后某日最高价超过成交买价5%，收盘后启用前日实体低点跟踪退出，"
        "跟踪线每天更新，不保证只升不降。盘中退出当日不回买主仓；当天另有0AMV离场条件仍转农行。",
        "农行从买入后的交易日起按5分钟K线检查费用后净价差8%止盈，分红不参与阈值；"
        "跳空越过阈值按开盘价卖出。止盈后现金锁定直到有效主仓入场；无独立止损。",
        "主仓60分钟K线检查止损；所有买入按100份/股取整，剩余现金与股息不自动增持。",
        f"主仓费用：{json.dumps(asdict(request.fees), ensure_ascii=False)}；"
        f"股票费用：{json.dumps(asdict(stock_fees), ensure_ascii=False)}。",
        "保留原固定印花税和过户费、除息日税前现金分红模型，未计个人股息税及到账延迟。"
        "ETF沿用本地输入价格口径，不另加现金分红；512100份额折算仅用于512100。",
        "legacy_same_close_idealized：0AMV信号在收盘后确认，同日收盘成交是理想化假设；"
        "未模拟涨跌停、停牌不可成交及盘口容量。",
        "年化按实际起止日间隔、365自然日复利；夏普按243交易日、零无风险利率；"
        "期末持仓按收盘价估值，不强制平仓。",
        "原主仓也在同一实际区间重跑，不能与不同区间或不同交易日时钟的旧结果直接比较。"
        "区间内必需交易日缺失报错，上市前不回填价格。", "",
        "根目录为新版；baseline/为同期原主仓。trades.csv为买卖流水，paired_trades.csv为闭合交易；"
        "inputs/、code_snapshot/及source_manifest.json保存实际输入、执行代码和SHA-256。", "",
    ]
    if excluded_sessions or excluded_zero_volume_bars:
        lines += ["## 交易日与停牌审计", "",
                  "采用两只ETF共同可交易日：已核实的全天停牌日期从两组时钟同时剔除，"
                  "0AMV指标仍在剔除前用完整历史计算。未知缺日继续报错。", ""]
        for event in excluded_sessions:
            lines.append(f"- {event['date']} {event['code']}：{event['reason']}。[公告]({event['source']})")
        if excluded_zero_volume_bars:
            lines.append(f"- 剔除 {len(excluded_zero_volume_bars)} 根零成交占位分钟线，不用其触发成交；详见calendar_audit.json。")
        lines += ["", "这是共同可交易日的比较口径，停牌日两组均不执行主仓或农行交易、不生成NAV；"
                  "跨过该日的价格变化在下一观察日体现，银行的盘中止盈也仅在保留日检查。"
                  "不等同于完整逐日停牌撮合模拟；不得与采用另一交易日时钟的旧结果直接相比。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    stock_files = [paths["stock_5m_dir"] / str(day.year) / f"{day:%Y%m%d}.parquet" for day in sorted(dates)]
    audit = {"code": DEFENSIVE_STOCK, "price_basis": "legacy_source_unchanged",
             "bar_count": len(stock), "source_files": [
                 {"path": str(path.resolve()), "size": path.stat().st_size,
                  "mtime_ns": path.stat().st_mtime_ns} for path in stock_files]}
    extra_inputs = {f"{BASELINE_PRIMARY}.csv": paths["baseline_primary_csv"],
                    "config.yaml": request.config_path}
    if calendar_policy_path is not None:
        extra_inputs["calendar_policy.json"] = calendar_policy_path
    extra_sources = ["python/strategies/amv_winning_defensive_csi2000/runner.py",
                     f"python/strategies/{request.task_id}/runner.py",
                     "python/strategies/amv_winning/bank_comparison.py"]
    if calendar_policy_path is not None and calendar_policy_path.resolve().is_relative_to(ROOT):
        extra_sources.append(calendar_policy_path.resolve().relative_to(ROOT).as_posix())
    snapshot_stock_inputs(
        output, stock, paths["stock_dividends_csv"], audit,
        amv_path=paths["amv_csv"], primary_path=paths["primary_csv"], primary_code=primary_code,
        extra_inputs=extra_inputs,
        extra_sources=tuple(extra_sources),
    )
    return output


if __name__ == "__main__":
    from python.run_backtest import main
    raise SystemExit(main(["run", "strategy", "amv_winning_defensive_csi2000", *sys.argv[1:]]))
